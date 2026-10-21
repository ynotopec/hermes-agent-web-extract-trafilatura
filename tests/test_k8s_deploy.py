"""Exercise deployment rendering without contacting a cluster."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


FAKE_KUBECTL = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
state = pathlib.Path(os.environ["DEPLOY_TEST_STATE"])
if args[:1] == ["-n"]:
    assert args[1] == "review-test", args
    args = args[2:]
if args[:2] == ["create", "configmap"]:
    data = {}
    for arg in args:
        if arg.startswith("--from-file="):
            key, path = arg[len("--from-file="):].split("=", 1)
            data[key] = pathlib.Path(path).read_text()
    print(json.dumps({"kind": "ConfigMap", "metadata": {"name": args[2]}, "data": data}))
elif args[:1] == ["patch"]:
    assert "--local" in args, args
    resource = json.load(sys.stdin)
    resource.update(json.loads(args[args.index("-p") + 1]))
    print(json.dumps(resource))
elif args[:1] == ["apply"]:
    path = args[args.index("-f") + 1]
    content = sys.stdin.read() if path == "-" else pathlib.Path(path).read_text()
    if content.startswith("{"):
        resource = json.loads(content)
        target = state / resource["metadata"]["name"]
        if target.exists():
            assert target.read_text() == content, "immutable data changed"
        target.write_text(content)
    elif "kind: Deployment" in content:
        (state / "deployment").write_text(content)
elif args[:1] == ["run"]:
    assert "--override-type=strategic" in args
    override = json.loads(next(a.split("=", 1)[1] for a in args if a.startswith("--overrides=")))
    (state / "health-security.json").write_text(json.dumps(override))
    assert "assert health" in sys.stdin.read()
elif args[:2] != ["rollout", "status"]:
    raise AssertionError(args)
'''


class DeploymentTest(unittest.TestCase):
    def test_revision_sources_are_retained_and_rendering_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path(__file__).resolve().parents[1]
            shutil.copytree(source / "k8s", root / "k8s")
            for name in ("server.py", "extraction.py", "requirements.lock"):
                (root / name).write_text('app = FastAPI(version="0.3.0")\n')
            state = root / "state"
            state.mkdir()
            binary = root / "bin"
            binary.mkdir()
            tool = binary / "kubectl"
            tool.write_text(FAKE_KUBECTL)
            tool.chmod(0o755)
            env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                       DEPLOY_TEST_STATE=str(state))

            def deploy():
                result = subprocess.run(
                    ["bash", str(root / "k8s/deploy.sh"), "review-test"],
                    env=env, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("http://trafilatura.review-test.svc.cluster.local:8990", result.stdout)
                return (state / "deployment").read_text()

            first = deploy()
            self.assertEqual(first, deploy())
            (root / "extraction.py").write_text("# revised extraction\n")
            second = deploy()
            self.assertNotEqual(first, second)
            maps = list(state.glob("trafilatura-server-*"))
            self.assertEqual(len(maps), 2)
            for path in maps:
                resource = json.loads(path.read_text())
                self.assertTrue(resource["immutable"])
                digest = hashlib.sha256("".join(resource["data"][name] for name in
                                        ("server.py", "extraction.py", "requirements.lock")).encode()).hexdigest()
                self.assertEqual(path.name, "trafilatura-server-" + digest)
                self.assertIn(path.name, first + second)
                self.assertIn(digest, first + second)
            # The original pod template still resolves its original source snapshot.
            original = next(path for path in maps if path.name in first)
            self.assertNotIn("# revised extraction", original.read_text())
            security = json.loads((state / "health-security.json").read_text())["spec"]
            self.assertTrue(security["securityContext"]["runAsNonRoot"])
            container = security["containers"][0]["securityContext"]
            self.assertFalse(container["allowPrivilegeEscalation"])
            self.assertEqual(container["capabilities"]["drop"], ["ALL"])
