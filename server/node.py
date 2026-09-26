"""Identity of this installation ("node") in the multi-PC system.

Everything lives in data/node/ and is never part of a backup restore:
  identity.json  node id, device name, role, epoch, cluster/authority information
  node.key       Ed25519 private key of this PC (signs every change it makes)
  tls.crt/.key   self-signed certificate for the encrypted sync connection
  authority.key  only on the administrator PC: signs user, permission and device changes
  state.json     the last change number this PC wrote (detects a rolled-back journal)

Roles: "unconfigured" (fresh copy, nothing decided yet), "authority" (the
administrator PC) and "member" (joined another administrator PC).

The "epoch" protects the numbering of this PC's own changes: whenever its history
might have been rolled back (restored journal, crash with lost writes) it continues
under a new origin "<node id>-<epoch>", so a change number is never used twice.
"""
import json
import os
import platform
import secrets
import uuid
from datetime import datetime

import ed25519
import tlscert

ROLES = ('unconfigured', 'authority', 'member')


def _now():
    return datetime.now().isoformat(timespec='seconds')


def write_atomic(path, data, mode=0o600):
    tmp = path + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, 'wb') as f:
        f.write(data if isinstance(data, bytes) else data.encode('utf-8'))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def machine_fingerprint():
    """Something that changes when the data folder is copied to another PC."""
    override = os.environ.get('BAMS_MACHINE_ID')
    if override:
        return override
    mac = uuid.getnode()
    mac = '' if (mac >> 40) & 1 else f'{mac:012x}'  # bit set = random value, not a real network card
    return f'{platform.node().lower()}|{mac}'


class Node:
    def __init__(self, data_dir, device_name=None):
        self.dir = os.path.join(data_dir, 'node')
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, 'identity.json')
        self.moved = False  # True when the folder seems to come from another PC
        if os.path.exists(self.path):
            with open(self.path, encoding='utf-8') as f:
                self.info = json.load(f)
            self._load_keys()
            if self.info.get('machine') != machine_fingerprint():
                self.moved = True
        else:
            self.info = None

    # ------------------------------------------------------------ creation
    @property
    def exists(self):
        return self.info is not None

    def create(self, device_name=None):
        """New identity for this PC. Called once (first start or 'set up as new device')."""
        node_id = secrets.token_hex(6)
        seed = ed25519.generate()
        write_atomic(os.path.join(self.dir, 'node.key'), seed.hex())
        cert, key, fp = tlscert.make_cert(seed, 'bams-' + node_id, int.from_bytes(os.urandom(8), 'big'))
        write_atomic(os.path.join(self.dir, 'tls.crt'), cert, 0o644)
        write_atomic(os.path.join(self.dir, 'tls.key'), key)
        self.info = {'node_id': node_id, 'name': (device_name or platform.node() or 'PC')[:60], 'created': _now(),
                     'machine': machine_fingerprint(), 'epoch': 1, 'role': 'unconfigured', 'cluster_id': None,
                     'authority_pub': None, 'authority_node': None, 'cert_fp': fp, 'old_replicas': []}
        self.save()
        self._load_keys()
        return self

    def _load_keys(self):
        with open(os.path.join(self.dir, 'node.key'), encoding='ascii') as f:
            self.seed = bytes.fromhex(f.read().strip())
        self.pub = ed25519.public_key(self.seed)
        ap = os.path.join(self.dir, 'authority.key')
        self.authority_seed = None
        if os.path.exists(ap):
            with open(ap, encoding='ascii') as f:
                self.authority_seed = bytes.fromhex(f.read().strip())
        self.tls_cert = os.path.join(self.dir, 'tls.crt')
        self.tls_key = os.path.join(self.dir, 'tls.key')

    def save(self):
        write_atomic(self.path, json.dumps(self.info, indent=2))

    # ------------------------------------------------------------ properties
    @property
    def id(self):
        return self.info['node_id']

    @property
    def name(self):
        return self.info['name']

    @property
    def role(self):
        return self.info['role']

    @property
    def replica(self):
        return f'{self.id}-{self.info["epoch"]}'

    @property
    def is_authority(self):
        return self.role == 'authority' and self.authority_seed is not None

    @property
    def authority_pub(self):
        a = self.info.get('authority_pub')
        return bytes.fromhex(a) if a else None

    @property
    def cert_fp(self):
        return self.info['cert_fp']

    def cert_pem(self):
        with open(self.tls_cert, encoding='ascii') as f:
            return f.read()

    # ------------------------------------------------------------ roles
    def become_authority(self):
        """The first administrator is created here: this PC becomes the administrator PC."""
        seed = ed25519.generate()
        write_atomic(os.path.join(self.dir, 'authority.key'), seed.hex())
        self.authority_seed = seed
        self.info.update(role='authority', cluster_id=secrets.token_hex(8), authority_pub=ed25519.public_key(seed).hex(),
                         authority_node=self.id)
        self.save()

    def join(self, cluster_id, authority_pub_hex, authority_node):
        self.info.update(role='member', cluster_id=cluster_id, authority_pub=authority_pub_hex, authority_node=authority_node)
        self.save()

    def install_authority_key(self, seed):
        """Recovery: this PC takes over the administrator key (exported from the old administrator PC)."""
        if ed25519.public_key(seed).hex() != self.info.get('authority_pub'):
            raise ValueError('This key does not belong to this system.')
        write_atomic(os.path.join(self.dir, 'authority.key'), seed.hex())
        self.authority_seed = seed
        self.info.update(role='authority', authority_node=self.id)
        self.save()

    def new_epoch(self, reason):
        self.info.setdefault('old_replicas', []).append({'replica': self.replica, 'ended': _now(), 'reason': reason})
        self.info['epoch'] += 1
        self.save()

    def confirm_same_machine(self):
        self.info['machine'] = machine_fingerprint()
        self.moved = False
        self.save()

    def set_name(self, name):
        self.info['name'] = str(name)[:60]
        self.save()

    # ------------------------------------------------------------ signing
    def sign(self, msg):
        return ed25519.sign(self.seed, msg, self.pub)

    def sign_authority(self, msg):
        if not self.authority_seed:
            raise PermissionError('Only the administrator PC can sign this change.')
        return ed25519.sign(self.authority_seed, msg)

    # ------------------------------------------------------------ own sequence guard
    def last_written(self):
        p = os.path.join(self.dir, 'state.json')
        if not os.path.exists(p):
            return {}
        try:
            with open(p, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def record_written(self, replica, cseq):
        st = self.last_written()
        if st.get(replica, 0) < cseq:
            st[replica] = cseq
            write_atomic(os.path.join(self.dir, 'state.json'), json.dumps(st))

    def public(self):
        return {'id': self.id, 'name': self.name, 'role': self.role, 'replica': self.replica, 'cluster': self.info.get('cluster_id'),
                'authority_node': self.info.get('authority_node'), 'cert_fp': self.cert_fp, 'moved': self.moved}
