import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DeploymentContractTests(unittest.TestCase):
    def test_required_deployment_files_exist(self):
        for name in [
            "Dockerfile",
            "compose.yaml",
            ".dockerignore",
            ".gitignore",
            ".env.example",
            "README.md",
        ]:
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).is_file())

    def test_compose_keeps_polling_private_and_persists_coins(self):
        compose = (ROOT / "compose.yaml").read_text()

        self.assertIn("restart: unless-stopped", compose)
        self.assertIn("init: true", compose)
        self.assertIn("env_file:", compose)
        self.assertIn("- .env", compose)
        self.assertIn("source: ./coins.json", compose)
        self.assertIn("target: /app/coins.json", compose)
        self.assertNotIn("ports:", compose)

    def test_dockerfile_uses_python_311_and_existing_entrypoint(self):
        dockerfile = (ROOT / "Dockerfile").read_text()

        self.assertIn("FROM python:3.11-slim", dockerfile)
        self.assertIn("COPY smc_bot ./smc_bot", dockerfile)
        self.assertIn('CMD ["python", "bot.py"]', dockerfile)

    def test_secrets_and_local_artifacts_are_ignored(self):
        gitignore = (ROOT / ".gitignore").read_text().splitlines()
        dockerignore = (ROOT / ".dockerignore").read_text().splitlines()

        for entry in [".env", ".deps/", "__pycache__/", "*.py[cod]"]:
            with self.subTest(entry=entry):
                self.assertIn(entry, gitignore)
                self.assertIn(entry, dockerignore)

    def test_example_environment_contains_names_without_secrets(self):
        lines = (ROOT / ".env.example").read_text().splitlines()

        self.assertEqual(
            lines,
            [
                "BYBIT_API_KEY=",
                "BYBIT_API_SECRET=",
                "TELEGRAM_BOT_TOKEN=",
                "TELEGRAM_CHAT_ID=",
            ],
        )

    def test_runtime_dependencies_are_pinned(self):
        requirements = (ROOT / "requirements.txt").read_text().splitlines()

        self.assertEqual(
            requirements,
            [
                "ccxt==4.5.58",
                "pandas==3.0.3",
                "numpy==2.4.6",
                "python-telegram-bot[job-queue]==22.8",
                "python-dotenv==1.2.2",
                "nest_asyncio==1.6.0",
            ],
        )


if __name__ == "__main__":
    unittest.main()
