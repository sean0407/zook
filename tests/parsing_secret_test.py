# -*- coding: utf-8 -*-
import re, unittest
from pathlib import Path

source = (Path(__file__).resolve().parents[1] / 'backend/zook/parsing.py').read_text(encoding='utf-8')
space = {'re': re}
exec(source[source.index('_SECRET_VALUE = '):source.index('def native_action')], space)
hide = space['hide_command_secrets']


class CommandSecrets(unittest.TestCase):
    def test_secrets_are_hidden(self):
        for text, secret in (('curl -H "Authorization: Bearer abcdef1234567890" https://x.io', 'abcdef1234567890'), ('export OPENAI_API_KEY=sk-abcdefghijklmnop1234', 'sk-abcdefghijklmnop1234'),
                             ('git clone https://me:hunter2pass@github.com/a/b', 'hunter2pass'), ('mysql --password=topsecret1 db', 'topsecret1'), ('TOKEN=plainvalue123 ./run.sh', 'plainvalue123'),
                             ('mysql --password "hunter2x" db', 'hunter2x'), ("tool --token 'abc12345'", 'abc12345'), ('tool --api-key "abc12345"', 'abc12345'), ('curl -u admin:hunter2x https://x.io', 'hunter2x'),
                             ('sshpass -p hunter2x ssh me@host', 'hunter2x'), ('mysql -phunter2x db', 'hunter2x'), ('curl -d "{\\"password\\":\\"hunter2x\\"}" x.io', 'hunter2x'), ('curl "https://x.io/a?key=abc12345&b=1"', 'abc12345'),
                             ('echo hf_abcdefghijklmnop', 'hf_abcdefghijklmnop'), ('echo AKIAABCDEFGHIJKLMNOP', 'AKIAABCDEFGHIJKLMNOP'), ('echo eyJhbGciOiJI.eyJzdWIiOiIx.abcdefgh', 'eyJhbGciOiJI'),
                             ('PASSWORD="correct horse battery" ./run', 'horse battery'), ('curl -H "Authorization: ApiKey abc123def" x.io', 'abc123def')):
            self.assertNotIn(secret, hide(text), text)

    def test_ordinary_commands_stay_readable(self):
        for text in ('git status', 'ls -la /Users/me/Documents', 'python3 tests/run.py --verbose', 'ssh -p 2222 me@host', 'grep -u foo bar.txt', 'mysql -h db -u root'): self.assertEqual(hide(text), text)


if __name__ == '__main__': unittest.main()
