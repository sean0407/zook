# -*- coding: utf-8 -*-
import re, unittest
from pathlib import Path

source = (Path(__file__).resolve().parents[1] / 'backend/zook/parsing.py').read_text(encoding='utf-8')
space = {'re': re}
exec(source[source.index('_COMMAND_SECRETS = ('):source.index('def native_action')], space)
hide = space['hide_command_secrets']


class CommandSecrets(unittest.TestCase):
    def test_secrets_are_hidden(self):
        for text, secret in (('curl -H "Authorization: Bearer abcdef1234567890" https://x.io', 'abcdef1234567890'), ('export OPENAI_API_KEY=sk-abcdefghijklmnop1234', 'sk-abcdefghijklmnop1234'),
                             ('git clone https://me:hunter2pass@github.com/a/b', 'hunter2pass'), ('mysql --password=topsecret1 db', 'topsecret1'), ('TOKEN=plainvalue123 ./run.sh', 'plainvalue123')):
            self.assertNotIn(secret, hide(text), text)

    def test_ordinary_commands_stay_readable(self):
        for text in ('git status', 'ls -la /Users/me/Documents', 'python3 tests/run.py --verbose'): self.assertEqual(hide(text), text)


if __name__ == '__main__': unittest.main()
