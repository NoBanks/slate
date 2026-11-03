import copy
import json

from slate.receipts import ReceiptChain, Signer, sha256_hex, verify_bundle


def make_bundle():
    chain = ReceiptChain("task-1", Signer.ephemeral())
    shot = b"\x89PNG fake screenshot"
    chain.append({"intent": "open vendor", "action": {"type": "goto", "url": "https://a.example"},
                  "observation": {"url": "https://a.example", "screenshot_sha256": sha256_hex(shot)}})
    chain.append({"intent": "type qty", "action": {"type": "type", "selector": "#qty", "value": "250"}})
    chain.finalize({"teardown": {"destroyed": True}, "approval": {"approved": True}})
    return chain.bundle(), {sha256_hex(shot): shot}


def test_valid_bundle_verifies():
    bundle, shots = make_bundle()
    report = verify_bundle(bundle, shots)
    assert report["ok"], report
    assert all(s["hash_ok"] and s["chain_ok"] and s["sig_ok"] for s in report["steps"])
    assert report["final_ok"]


def test_survives_json_roundtrip():
    bundle, _ = make_bundle()
    assert verify_bundle(json.loads(json.dumps(bundle)))["ok"]


def test_one_byte_tamper_breaks_chain():
    bundle, _ = make_bundle()
    bad = copy.deepcopy(bundle)
    bad["receipts"][0]["intent"] = "open vendoR"
    report = verify_bundle(bad)
    assert not report["ok"]
    assert report["steps"][0]["hash_ok"] is False
    assert "step 1" in report["error"]


def test_rehash_without_key_fails_signature():
    # An attacker edits a receipt and recomputes its hash, but cannot re-sign it.
    from slate.receipts import canonical
    bundle, _ = make_bundle()
    bad = copy.deepcopy(bundle)
    r = bad["receipts"][1]
    r["action"]["value"] = "9999"
    body = {k: v for k, v in r.items() if k not in ("hash", "sig")}
    r["hash"] = sha256_hex(canonical(body))
    report = verify_bundle(bad)
    assert not report["ok"]
    assert report["steps"][1]["sig_ok"] is False


def test_dropped_step_breaks_chain():
    bundle, _ = make_bundle()
    bad = copy.deepcopy(bundle)
    del bad["receipts"][1]
    report = verify_bundle(bad)
    assert not report["ok"]
    assert report["steps"][1]["chain_ok"] is False


def test_wrong_pubkey_fails():
    bundle, _ = make_bundle()
    bad = copy.deepcopy(bundle)
    bad["pubkey"] = Signer.ephemeral().pubkey_hex
    assert not verify_bundle(bad)["ok"]


def test_swapped_screenshot_detected():
    bundle, shots = make_bundle()
    k = next(iter(shots))
    report = verify_bundle(bundle, {k: b"different image"})
    assert not report["ok"]
    assert report["steps"][0]["screenshot_ok"] is False


def test_garbage_input():
    assert not verify_bundle({"nope": 1})["ok"]
    assert not verify_bundle({"format": "slate-bundle/1"})["ok"]
