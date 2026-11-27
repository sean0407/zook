# Conversations on disk: one file per conversation, beside a main file that holds everything else. In memory nothing changes:
# every message list is where it always was. Saving writes the main file and only the conversations that changed, so the time a
# save takes no longer grows with everything that was ever said. Loaded by backend/server.py into one shared namespace.
#
# chats/<bot id>/<chat id>.json   one conversation of a Bot (also of a Bot kept aside after deletion)
# chats/group.<group id>.json     one group's discussion
#
# The main file carries "layout": 2. A file without it (older data, a backup, a file another Mac wrote) has every conversation
# inside it and is the whole truth: its conversations are written out as files and the main file is then saved in the new form.
import gzip, datetime

CHAT_LAYOUT = 2
CHAT_FOLDER = 'chats'
CHAT_SWEEP_EVERY = 60    # seconds between looks at every conversation, for a change nobody announced
CHAT_HOT_SECONDS = 120   # a conversation is checked in full on every save while it is being replied to, and this long after
_CHAT_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}')


def _chat_name(value):
    value = str(value)
    return value if _CHAT_NAME.fullmatch(value) else 'x' + hashlib.sha1(value.encode('utf-8', 'replace')).hexdigest()


def chats_on_disk(directory):
    """True when the conversation folder holds at least one conversation."""
    root = pathlib.Path(directory) / CHAT_FOLDER
    try: return root.is_dir() and not root.is_symlink() and any(p.suffix == '.json' for p in root.rglob('*.json'))
    except OSError: return False


def chat_conversations(data):
    """Every conversation in the data as (key, relative path, the message list, the record that owns it).
    The key is (owner id, chat id); a group's chat id is ''."""
    out, owners = [], set()
    for kind in ('bots', 'deletedBots'):
        for bot in data.get(kind) or []:
            if not isinstance(bot, dict) or not isinstance(bot.get('id'), str) or bot['id'] in owners: continue  # an id that is listed twice is only stored once: the first, which is the live Bot
            owners.add(bot['id'])
            chats = bot.get('chats') if isinstance(bot.get('chats'), list) else []
            open_id = bot.get('chatId')
            if not chats:  # a Bot from before there were several conversations (some that were deleted long ago still look like this): its one list
                if isinstance(bot.get('messages'), list): out.append(((bot['id'], 'main'), '%s/main.json' % _chat_name(bot['id']), bot['messages'], bot))
                continue
            mine = set()
            for chat in chats:
                if not isinstance(chat, dict) or not isinstance(chat.get('id'), str) or chat['id'] in mine: continue
                mine.add(chat['id'])
                messages = bot.get('messages') if chat['id'] == open_id else chat.get('messages')
                out.append(((bot['id'], chat['id']), '%s/%s.json' % (_chat_name(bot['id']), _chat_name(chat['id'])), messages if isinstance(messages, list) else [], chat))
    for group in data.get('groups') or []:
        if isinstance(group, dict) and isinstance(group.get('id'), str) and ('group', group['id']) not in owners:
            owners.add(('group', group['id']))
            out.append(((group['id'], ''), 'group.%s.json' % _chat_name(group['id']), group.get('messages') if isinstance(group.get('messages'), list) else [], group))
    return out


def chat_strip(data):
    """The main file: the data without any message, and with how many each conversation has (so a missing file is noticed)."""
    def bot_part(bot):
        if not isinstance(bot, dict): return bot
        out = {k: v for k, v in bot.items() if k != 'messages'}
        if isinstance(bot.get('chats'), list):
            out['chats'] = [dict({k: v for k, v in c.items() if k != 'messages'}, stored=len((bot.get('messages') if c.get('id') == bot.get('chatId') else c.get('messages')) or [])) if isinstance(c, dict) else c for c in bot['chats']]
        else: out['stored'] = len(bot.get('messages') or [])
        return out
    out = dict(data, layout=CHAT_LAYOUT)
    for kind in ('bots', 'deletedBots'):
        if isinstance(data.get(kind), list): out[kind] = [bot_part(b) for b in data[kind]]
    if isinstance(data.get('groups'), list):
        out['groups'] = [dict({k: v for k, v in g.items() if k != 'messages'}, stored=len(g.get('messages') or [])) if isinstance(g, dict) else g for g in data['groups']]
    return out


def _chat_light(messages):
    """A quick mark of a conversation that changes when a message is added, removed, finished or rewritten. Cheap enough to take of everything."""
    try: return hash(tuple((m.get('id'), m.get('status'), m.get('content'), m.get('note'), len(m)) if isinstance(m, dict) else None for m in messages))
    except TypeError: return hash(repr(messages))  # a field that should be text is not (data brought in from a file): still never an error


def _write_whole(path, text):
    """Replace a file in one step: after a crash it is either the old file or the new one, never half of each."""
    fd, name = tempfile.mkstemp(prefix='.w-', dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


class ChatFiles:
    """Mixed into Store."""
    keep_aside = False  # True while a backup is being put back: the conversations that were there stay in chats.old until it has worked

    def chat_root(self): return self.dir / CHAT_FOLDER

    def chat_touch(self, owner_id):
        """Something about this Bot's or group's conversations may have changed; look at them in full at the next save."""
        self.__dict__.setdefault('_chat_touched', set()).add(owner_id)

    def chat_forget(self):
        """What this Store believes is on disk is no longer true (the folder was replaced): start again from nothing."""
        for cache in ('_chat_written', '_chat_lights', '_chat_sizes', '_chat_hot', '_chat_touched', '_chat_known', '_chat_failed'): self.__dict__.pop(cache, None)

    def _chat_write(self, key, rel, messages, root=None):
        """Write one conversation if it differs from what is on disk. Returns True when it wrote."""
        text = json.dumps(dict(owner=key[0], id=key[1], messages=messages), ensure_ascii=False)
        mark = hashlib.sha1(text.encode('utf-8', 'surrogatepass')).digest()
        written = self.__dict__.setdefault('_chat_written', {})
        if root is None:
            self.__dict__.setdefault('_chat_lights', {})[key] = _chat_light(messages); self.__dict__.setdefault('_chat_sizes', {})[key] = len(messages)
            if written.get(key) == mark: return False
        path = (root or self.chat_root()) / rel
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_whole(path, text)
        if root is None: written[key] = mark
        return True

    def save_chats(self, everything=False):
        """Lock held. Which conversations are looked at:
        - in full, on every save: the ones being replied to (and for two minutes after), and the ones a request named;
        - on every save, by length: all of them, so an added or removed message is never missed;
        - once a minute, by a quick mark of every message: all of them, for a change in place that nobody announced.
        everything=True compares all of them in full. A conversation that existed during this run and is gone has its file removed;
        a file this run never knew about is never removed here."""
        now = time.monotonic(); hot = self.__dict__.setdefault('_chat_hot', {}); lights = self.__dict__.setdefault('_chat_lights', {})
        sizes = self.__dict__.setdefault('_chat_sizes', {}); written = self.__dict__.setdefault('_chat_written', {})
        for job in self.data.get('jobs') or []:
            if job.get('status') == 'running': hot[(job.get('groupId') or job.get('botId'), '' if job.get('groupId') else job.get('chatId'))] = now
        for key in [k for k, at in hot.items() if now - at > CHAT_HOT_SECONDS]: del hot[key]
        touched, self._chat_touched = self.__dict__.get('_chat_touched') or set(), set()  # taken in one step: a request may be naming another owner right now
        sweep = everything or now - self.__dict__.get('_chat_swept', 0) >= CHAT_SWEEP_EVERY
        wrote, seen, failed = 0, {}, []
        for key, rel, messages, _ in chat_conversations(self.data):
            seen[rel] = key
            if not messages and key not in written: continue  # never had anything: no file
            full = everything or key in hot or (key[0], None) in hot or key[0] in touched or sizes.get(key) != len(messages)
            if not full and not (sweep and lights.get(key) != _chat_light(messages)): continue
            try: wrote += self._chat_write(key, rel, messages)
            except OSError as exc: failed.append((key, rel, str(exc)))  # one file that cannot be written must not stop the others, nor the main file
        known = self.__dict__.setdefault('_chat_known', {})
        for rel, key in list(known.items()):
            if rel in seen: continue
            try: os.unlink(str(self.chat_root() / rel))  # deleted during this run
            except OSError: pass
            if '/' in rel:
                try: os.rmdir(str((self.chat_root() / rel).parent))
                except OSError: pass
            for cache in (written, lights, sizes): cache.pop(key, None)
            del known[rel]
        known.update(seen)
        if sweep: self._chat_swept = now
        self.chat_failures(failed)
        return wrote

    def chat_failures(self, failed):
        """Say once, in the activity record, which conversation could not be written; it is tried again at every save."""
        before = self.__dict__.get('_chat_failed') or set(); now = {rel for _, rel, _ in failed}
        for key, rel, why in failed:
            self.__dict__.setdefault('_chat_touched', set()).add(key[0])
            if rel not in before:
                try: log_activity(self, 'backup', '對話檔 %s 寫不進去（%s），之後每次存檔都會再試' % (rel, why[:120]), by='Zook')
                except Exception: pass
        self._chat_failed = now

    def chats_split(self, first):
        """The data in memory holds every conversation (older data, or a backup put back). Write them all out as files and only
        then save the main file in the new form. Until that last step the old main file is untouched, so stopping halfway loses nothing."""
        root, fresh, aside = self.chat_root(), self.dir / (CHAT_FOLDER + '.new'), self.dir / (CHAT_FOLDER + '.old')
        if first and self.path.exists():  # the very first time: the data as it was stays on disk under another name, and as a backup
            kept = self.dir / 'swarmr-before-split.json'
            if not kept.exists(): shutil.copy2(str(self.path), str(kept))
            if any(messages for _, _, messages, _ in chat_conversations(self.data)): backup_write(self, 'safety', self.data)
        for stale in (fresh, aside):
            if stale.is_symlink(): stale.unlink()
            else: shutil.rmtree(str(stale), ignore_errors=True)
        fresh.mkdir(mode=0o700)
        try:
            for key, rel, messages, _ in chat_conversations(self.data):
                if messages: self._chat_write(key, rel, messages, root=fresh)
            if root.is_symlink(): root.unlink()
            elif root.exists(): os.replace(str(root), str(aside))
            os.replace(str(fresh), str(root))
            try: self.save_main()
            except BaseException:
                shutil.rmtree(str(root), ignore_errors=True)
                if aside.exists(): os.replace(str(aside), str(root))
                raise
        finally: shutil.rmtree(str(fresh), ignore_errors=True)
        if not self.keep_aside: shutil.rmtree(str(aside), ignore_errors=True)
        self.chat_forget()
        self.save_chats(everything=True)  # every file was just written: this only notes what is on disk

    def chats_load(self, overlay=False):
        """Fill every conversation from its file. overlay=True is for data that came from a backup while the files are still there:
        a file then wins over what the backup had. Returns the conversations that could not be read."""
        root, damaged = self.chat_root(), []
        for leftover in (CHAT_FOLDER + '.new', CHAT_FOLDER + '.old'): shutil.rmtree(str(self.dir / leftover), ignore_errors=True)
        alive = {b.get('id') for b in self.data.get('bots') or [] if isinstance(b, dict)}
        if isinstance(self.data.get('deletedBots'), list): self.data['deletedBots'] = [b for b in self.data['deletedBots'] if not isinstance(b, dict) or b.get('id') not in alive]  # a Bot is either here or kept aside, never both: the two would share one file
        for kind in ('bots', 'deletedBots'):
            for bot in self.data.get(kind) or []:
                if isinstance(bot, dict) and not isinstance(bot.get('messages'), list): bot['messages'] = []
                for chat in (bot.get('chats') if isinstance(bot, dict) and isinstance(bot.get('chats'), list) else []):
                    if isinstance(chat, dict) and chat.get('id') != bot.get('chatId') and not isinstance(chat.get('messages'), list): chat['messages'] = []
        for group in self.data.get('groups') or []:
            if isinstance(group, dict) and not isinstance(group.get('messages'), list): group['messages'] = []
        for key, rel, inline, record in chat_conversations(self.data):
            expected = record.pop('stored', None) if isinstance(record, dict) else None
            path, found, bad = root / rel, None, False
            try:
                if path.is_symlink(): raise OSError('a link, not a file')
                raw = path.read_bytes(); stored = json.loads(raw.decode('utf-8'))
                found = stored.get('messages') if isinstance(stored, dict) else None
                if not isinstance(found, list) or any(not isinstance(m, dict) for m in found): found, bad = None, True
                else: self.__dict__.setdefault('_chat_written', {})[key] = hashlib.sha1(raw).digest()  # as it is on disk: not written again unless it changes
            except FileNotFoundError: pass
            except (OSError, ValueError, UnicodeError, RecursionError): bad = True
            if bad:
                try: os.replace(str(path), str(path) + '.damaged')
                except OSError: pass
            if found is not None:
                if overlay: inline[:] = found
                else:  # an older Zook that opened this data wrote its new messages into the main file: they belong after the file's
                    have = {m.get('id') for m in found}; extra = [m for m in inline if isinstance(m, dict) and m.get('id') not in have]
                    inline[:] = found + extra
            elif bad or (expected and not inline): damaged.append((key, record))
        return damaged

    def save_main(self):
        fd, name = tempfile.mkstemp(prefix='.swarmr-', dir=str(self.dir))
        try:
            os.fchmod(fd, 0o600)
            self.data['savedAt'] = NOW()  # about when Zook last stopped, read at the next start (resume.py); a backup keeps its own
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(chat_strip(self.data), f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name): os.unlink(name)


def chats_from_backups(store, damaged):
    """Conversations whose file could not be read are looked up in the newest backup that has them. Returns what to tell the user."""
    notes, wanted = [], {key: record for key, record in damaged}
    def name_of(key):
        owner = next((x for x in (store.data.get('bots') or []) + (store.data.get('deletedBots') or []) + (store.data.get('groups') or []) if isinstance(x, dict) and x.get('id') == key[0]), {})
        record = wanted.get(key) or {}
        return ' · '.join(x for x in (str(owner.get('name') or 'Bot'), str(record.get('title') or '') if key[1] else '') if x)
    current = {key: messages for key, rel, messages, _ in chat_conversations(store.data)}
    for backup in backup_list(store) if wanted else []:
        path = backup_path(store, backup['name'])
        if backup['kind'] == 'file' or not path or backup_too_big(path): continue
        try: old = backup_check(backup_read(path))
        except (OSError, ValueError, UnicodeError, RecursionError, EOFError, KeyError, _zipfile.BadZipFile): continue
        for key, rel, messages, _ in chat_conversations(old):
            if key in wanted and messages and key in current:
                current[key][:] = messages; notes.append(dict(name=name_of(key), backup=backup['name'], backupAt=backup['at'])); del wanted[key]
        if not wanted: break
    notes += [dict(name=name_of(key), backup='', backupAt='') for key in wanted]
    for note in notes: log_activity(store, 'backup', '對話「%s」的檔案無法讀取，%s' % (note['name'], '已改用備份 ' + note['backup'] if note['backup'] else '沒有備份可用，這個對話目前是空的'), by='Zook')
    return notes


def backup_read(path):
    """A backup as data. New ones are compressed; older ones are plain."""
    with open(str(path), 'rb') as f: head = f.read(2)
    if head == b'PK':  # a backup with files: its data part (backupplus.py)
        with _zipfile.ZipFile(str(path)) as z, z.open('data.json') as f: raw = f.read(8 * MAX_BACKUP_FILE + 1)
        if len(raw) > 8 * MAX_BACKUP_FILE: raise ValueError('備份檔太大。')
        return json.loads(raw.decode('utf-8'))
    if head == b'\x1f\x8b':
        with gzip.open(str(path), 'rb') as f: raw = f.read(8 * MAX_BACKUP_FILE + 1)
        if len(raw) > 8 * MAX_BACKUP_FILE: raise ValueError('備份檔太大。')
        return json.loads(raw.decode('utf-8'))
    with open(str(path), encoding='utf-8') as f: return json.load(f)


class Store(AuditTrail, ChatFiles, StoreBase):  # AuditTrail: auditlog.py
    """The data in memory and on disk. StoreBase (core.py) loads and upgrades it; this part keeps the conversations in their files."""
    def load_conversations(self, existed, layout, recovered):
        """Called while loading, before the upgrades. Decides where the conversations come from."""
        root = self.chat_root(); damaged = []
        if recovered is not None:
            # The main file was unreadable. Whatever replaced it (a backup, or a fresh start), the conversation files are still there and are newer.
            if root.is_dir():
                damaged = self.chats_load(overlay=True); adopted = self.chats_adopt()
                recovered['chatsKept'] = True; recovered['adopted'] = adopted
            else: self._split_due = True; self._split_first = False
        elif not existed: pass  # a fresh start: nothing to read
        elif layout == CHAT_LAYOUT:
            damaged = self.chats_load()
            if root.is_dir(): self.chats_adopt()  # the main file may be an older copy put back by hand: files it does not list are kept, never deleted
        else: self._split_due = True; self._split_first = not root.exists()
        if damaged: self._chat_damaged = damaged

    def chats_adopt(self):
        """After the main file was replaced by an older copy: a conversation file of a known Bot that the copy does not list is put
        back into that Bot's list. Files of Bots and groups the copy does not know are moved aside, never deleted. Returns how many were put back."""
        root, count = self.chat_root(), 0
        bots = {_chat_name(b['id']): b for b in (self.data.get('bots') or []) + (self.data.get('deletedBots') or []) if isinstance(b, dict) and isinstance(b.get('id'), str)}
        groups = {'group.%s.json' % _chat_name(g['id']) for g in self.data.get('groups') or [] if isinstance(g, dict) and isinstance(g.get('id'), str)}
        aside = self.dir / ('chats.unlisted-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        def keep(path):
            aside.mkdir(mode=0o700, exist_ok=True)
            try: os.replace(str(path), str(aside / path.name))
            except OSError: pass
        if root.is_symlink(): return 0
        for entry in sorted(root.iterdir()):
            if entry.is_symlink() or entry.name.endswith('.damaged') or entry.name.startswith('.'): continue
            if entry.is_file():
                if entry.name.startswith('group.') and entry.name.endswith('.json') and entry.name not in groups: keep(entry)
                continue
            bot = bots.get(entry.name)
            if bot is None: keep(entry); continue
            if not bot.get('chats'): continue  # a Bot with a single list has only its one file
            listed = {_chat_name(c['id']) for c in bot['chats'] if isinstance(c, dict) and isinstance(c.get('id'), str)}
            for item in sorted(entry.glob('*.json')):
                if item.stem in listed: continue
                try:
                    stored = json.loads(item.read_text(encoding='utf-8')); messages = stored['messages']
                    if not isinstance(stored.get('id'), str) or _chat_name(stored['id']) != item.stem or not isinstance(messages, list) or any(not isinstance(m, dict) for m in messages): raise ValueError
                except (OSError, ValueError, KeyError, TypeError, UnicodeError, RecursionError): continue
                first = next((m for m in messages if m.get('role') == 'user' and isinstance(m.get('content'), str)), None)
                stamp = next((m.get('createdAt') for m in reversed(messages) if m.get('createdAt')), None) or NOW()
                bot['chats'].append(dict(id=stored['id'], title=chat_title(first['content']) if first else '', createdAt=(messages[0].get('createdAt') if messages else None) or stamp, updatedAt=stamp, messages=messages)); count += 1
        return count

    def note_damaged(self):
        """After loading: conversations whose file could not be read are looked up in the backups, and the user is told which."""
        damaged = self.__dict__.pop('_chat_damaged', None)
        if not damaged: return
        notes = chats_from_backups(self, damaged)
        note = self.data['settings'].get('recovered') or dict(at=NOW(), backup='', backupAt='', kept='', chatsOnly=True)
        note['chats'] = notes; self.data['settings']['recovered'] = note
