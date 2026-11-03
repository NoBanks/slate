"""Hash-chained, Ed25519-signed receipts.

Every receipt body is serialized canonically (sorted keys, no whitespace),
chained to the previous receipt by `prev_hash`, hashed with SHA-256, and the
hash is signed with the server's Ed25519 key. Anyone holding a bundle and the
public key can re-check every link without trusting the server.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nacl.encoding import HexEncoder
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

BUNDLE_FORMAT = "slate-bundle/1"
SEALED_FIELDS = ("hash", "sig")


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def genesis_hash(task_id: str) -> str:
    return sha256_hex(f"SLATE-GENESIS:{task_id}".encode())


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Signer:
    """Server identity. The private key never leaves the control plane."""

    def __init__(self, key: SigningKey):
        self._key = key

    @classmethod
    def load_or_create(cls, path: Path) -> "Signer":
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return cls(SigningKey(path.read_bytes().strip(), encoder=HexEncoder))
        key = SigningKey.generate()
        path.write_bytes(key.encode(encoder=HexEncoder))
        return cls(key)

    @classmethod
    def ephemeral(cls) -> "Signer":
        return cls(SigningKey.generate())

    @property
    def pubkey_hex(self) -> str:
        return self._key.verify_key.encode(encoder=HexEncoder).decode()

    def sign_hex(self, digest_hex: str) -> str:
        sig = self._key.sign(bytes.fromhex(digest_hex)).signature
        return "ed25519:" + base64.b64encode(sig).decode()


def seal(body: dict, prev_hash: str, signer: Signer) -> dict:
    receipt = {k: v for k, v in body.items() if k not in SEALED_FIELDS}
    receipt["prev_hash"] = prev_hash
    digest = sha256_hex(canonical(receipt))
    receipt["hash"] = digest
    receipt["sig"] = signer.sign_hex(digest)
    return receipt


class ReceiptChain:
    def __init__(self, task_id: str, signer: Signer):
        self.task_id = task_id
        self.signer = signer
        self.receipts: list[dict] = []

    @property
    def head(self) -> str:
        return self.receipts[-1]["hash"] if self.receipts else genesis_hash(self.task_id)

    def append(self, body: dict) -> dict:
        body = dict(body)
        body.setdefault("task_id", self.task_id)
        body.setdefault("step", len(self.receipts) + 1)
        body.setdefault("ts", now_iso())
        r = seal(body, self.head, self.signer)
        self.receipts.append(r)
        return r

    def finalize(self, final: dict) -> dict:
        body = {"kind": "final", **final, "total_steps": len(self.receipts)}
        return self.append(body)

    def bundle(self) -> dict:
        return {
            "format": BUNDLE_FORMAT,
            "task_id": self.task_id,
            "pubkey": self.signer.pubkey_hex,
            "chain_root": self.head,
            "receipts": self.receipts,
        }


def verify_signature(pubkey_hex: str, digest_hex: str, sig: str) -> bool:
    try:
        if not sig.startswith("ed25519:"):
            return False
        VerifyKey(pubkey_hex, encoder=HexEncoder).verify(
            bytes.fromhex(digest_hex), base64.b64decode(sig[len("ed25519:"):]))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False


def verify_bundle(bundle: dict, screenshots: dict[str, bytes] | None = None) -> dict:
    """Re-check every receipt. Returns a per-step report; ok only if everything holds."""
    out: dict[str, Any] = {"ok": False, "pubkey": None, "steps": [], "final_ok": False}
    try:
        if bundle.get("format") != BUNDLE_FORMAT:
            out["error"] = "unknown bundle format"
            return out
        pubkey = bundle["pubkey"]
        task_id = bundle["task_id"]
        receipts = bundle["receipts"]
    except (KeyError, TypeError, AttributeError):
        out["error"] = "malformed bundle"
        return out
    out["pubkey"] = pubkey
    prev = genesis_hash(task_id)
    all_ok = bool(receipts)
    for r in receipts:
        body = {k: v for k, v in r.items() if k not in SEALED_FIELDS}
        recomputed = sha256_hex(canonical(body))
        hash_ok = recomputed == r.get("hash")
        chain_ok = r.get("prev_hash") == prev and r.get("task_id") == task_id
        sig_ok = verify_signature(pubkey, r.get("hash", ""), r.get("sig", ""))
        row = {"step": r.get("step"), "hash_ok": hash_ok, "chain_ok": chain_ok, "sig_ok": sig_ok}
        shot = (r.get("observation") or {}).get("screenshot_sha256")
        if screenshots is not None and shot:
            row["screenshot_ok"] = shot in screenshots and sha256_hex(screenshots[shot]) == shot
            all_ok &= row["screenshot_ok"]
        out["steps"].append(row)
        all_ok &= hash_ok and chain_ok and sig_ok
        prev = r.get("hash")
    last = receipts[-1] if receipts else {}
    out["final_ok"] = last.get("kind") == "final" and bundle.get("chain_root") == last.get("hash")
    out["ok"] = bool(all_ok and out["final_ok"])
    if not out["ok"] and "error" not in out:
        bad = [s["step"] for s in out["steps"] if not (s["hash_ok"] and s["chain_ok"] and s["sig_ok"])]
        out["error"] = f"chain broken at step {bad[0]}" if bad else "final receipt missing or chain_root mismatch"
    return out
