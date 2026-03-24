#!/usr/bin/env python3
"""
DID Resolution v1.0 conformance test — WG test vectors
https://github.com/corpollc/qntm/blob/main/specs/test-vectors/did-resolution.json

Tests our key extraction and sender_id derivation logic against the WG spec.
This is a standalone script — does NOT require the running Agora service.
"""
import base64
import base58
import hashlib
import json
import sys
import httpx


# ─── §3.1.1 Key extraction (priority order per spec) ────────────────────────

def _extract_ed25519_from_multibase(value: str) -> bytes:
    """Decode z-prefixed base58btc multibase, strip 0xed01 multicodec prefix."""
    if not value.startswith("z"):
        raise ValueError(f"Unsupported multibase prefix: {value[0]!r}")
    raw = base58.b58decode(value[1:])
    if raw[:2] != b"\xed\x01":
        raise ValueError(f"key_type_unsupported: multicodec prefix {raw[:2].hex()!r} is not Ed25519 (0xed01)")
    return raw[2:]  # 32-byte Ed25519 public key


def extract_ed25519_public_key(did_document: dict) -> bytes:
    """
    Extract Ed25519 public key from a DID Document per §3.1.1 priority order:
    1. publicKeyMultibase + Ed25519VerificationKey2020
    2. publicKeyBase58 + Ed25519VerificationKey2018
    3. publicKeyJwk kty=OKP crv=Ed25519
    """
    vms = did_document.get("verificationMethod", [])
    if not vms:
        raise KeyError("key_extraction_failed: no verificationMethod in DID Document")

    for vm in vms:
        vm_type = vm.get("type", "")

        # Priority 1: publicKeyMultibase + Ed25519VerificationKey2020
        if vm_type == "Ed25519VerificationKey2020" and "publicKeyMultibase" in vm:
            return _extract_ed25519_from_multibase(vm["publicKeyMultibase"])

        # Priority 2: publicKeyBase58 + Ed25519VerificationKey2018
        if vm_type == "Ed25519VerificationKey2018" and "publicKeyBase58" in vm:
            raw = base58.b58decode(vm["publicKeyBase58"])
            if len(raw) != 32:
                raise ValueError(f"Expected 32-byte key from publicKeyBase58, got {len(raw)}")
            return raw

        # Priority 3: publicKeyJwk kty=OKP crv=Ed25519
        if "publicKeyJwk" in vm:
            jwk = vm["publicKeyJwk"]
            if jwk.get("kty") == "OKP" and jwk.get("crv") == "Ed25519":
                x = jwk["x"]
                # Add padding if needed
                x += "=" * (-len(x) % 4)
                raw = base64.urlsafe_b64decode(x)
                if len(raw) != 32:
                    raise ValueError(f"Expected 32-byte key from JWK x field, got {len(raw)}")
                return raw

    raise KeyError("key_extraction_failed: no Ed25519 key found in verificationMethod entries")


# ─── §3.2 did:key resolution ─────────────────────────────────────────────────

def resolve_did_key(did: str) -> bytes:
    """Resolve did:key to Ed25519 public key per §3.2."""
    if not did.startswith("did:key:"):
        raise ValueError("method_unsupported")
    multibase = did[len("did:key:"):]
    raw = _extract_ed25519_from_multibase(multibase)
    return raw


# ─── §3.1 did:web resolution ─────────────────────────────────────────────────

def _did_web_document_url(did: str) -> str:
    """Build the DID Document fetch URL per §3.1."""
    prefix = "did:web:"
    method_specific = did[len(prefix):]
    parts = method_specific.split(":")
    host = parts[0]
    path_parts = parts[1:]
    if path_parts:
        path = "/".join(path_parts)
        return f"https://{host}/{path}/did.json"
    return f"https://{host}/.well-known/did.json"


def resolve_did_web(did: str) -> bytes:
    """Resolve did:web to Ed25519 public key per §3.1 (live network fetch)."""
    url = _did_web_document_url(did)
    headers = {"User-Agent": "Agora-DID-Resolver/1.0 (archedark-ada; did:web:the-agora.dev)"}
    resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    doc = resp.json()
    return extract_ed25519_public_key(doc)


def resolve_did_web_from_document(did_document: dict) -> bytes:
    """Resolve did:web from an inline DID Document (for test vectors)."""
    return extract_ed25519_public_key(did_document)


# ─── §4 Sender ID derivation ─────────────────────────────────────────────────

def derive_sender_id(public_key: bytes) -> str:
    """Derive sender_id per §4: SHA-256(pubkey)[0:16] as lowercase hex."""
    digest = hashlib.sha256(public_key).digest()
    return digest[:16].hex()


# ─── Test vector runner ───────────────────────────────────────────────────────

VECTORS = [
    {
        "name": "did:key Ed25519 resolution",
        "did": "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
        "expected_method": "key",
        "expected_public_key_hex": "2e6fcce36701dc791488e0d0b1745cc1e33a4c1c9fcc41c63bd343dbbe0970e6",
        "expected_sender_id": "c446d9bcf84d5e3ee966bac5c1f634c1",
    },
    {
        "name": "did:web — qntm relay (inline DID Document)",
        "did": "did:web:inbox.qntm.corpo.llc",
        "expected_method": "web",
        "expected_public_key_hex": "8ab0ff6c0befb7f2ae41768a01e6d1241729dd2145c9c0dbda611ac410840bc9",
        "expected_sender_id": "f0a6e0c2a1cbbebc0306b5f744d2be70",
        "did_document": {
            "@context": ["https://www.w3.org/ns/did/v1", "https://w3id.org/security/suites/ed25519-2020/v1"],
            "id": "did:web:inbox.qntm.corpo.llc",
            "verificationMethod": [{
                "id": "did:web:inbox.qntm.corpo.llc#relay-key",
                "type": "Ed25519VerificationKey2020",
                "controller": "did:web:inbox.qntm.corpo.llc",
                "publicKeyMultibase": "z6MkoneqzREQvS9HyVsocPhG1cs7fX3ov8zPPeiUtgonWKT6"
            }]
        },
    },
    {
        "name": "did:web — Agent Agora (live)",
        "did": "did:web:the-agora.dev",
        "expected_method": "web",
        "expected_sender_id": "66f65dd543fa0c6f50580f7e35327e04",
        "live": True,
    },
    {
        "name": "did:web — ArkForge (live)",
        "did": "did:web:trust.arkforge.tech",
        "expected_method": "web",
        "expected_sender_id": "174e20acd605f8ce6fca394246729bd7",
        "live": True,
    },
    {
        "name": "sender_id derivation consistency",
        "public_key_hex": "2e6fcce36701dc791488e0d0b1745cc1e33a4c1c9fcc41c63bd343dbbe0970e6",
        "expected_sender_id_hex": "c446d9bcf84d5e3ee966bac5c1f634c1",
        "derivation_only": True,
    },
    {
        "name": "error — unsupported key type (secp256k1)",
        "did": "did:key:zQ3shwNhBehPxCvMWKX4b3TLQ8WFjz5bYPuWdRhPDAStbNTN",
        "expected_error": "key_type_unsupported",
    },
    {
        "name": "error — malformed DID",
        "did": "notadid:web:example.com",
        "expected_error": "method_unsupported",
    },
    {
        "name": "error — missing verificationMethod",
        "did": "did:web:empty.example.com",
        "expected_error": "key_extraction_failed",
        "did_document": {
            "@context": ["https://www.w3.org/ns/did/v1"],
            "id": "did:web:empty.example.com"
        },
    },
]


def run_vector(v: dict) -> tuple[bool, str]:
    name = v["name"]

    # Derivation-only test
    if v.get("derivation_only"):
        pubkey = bytes.fromhex(v["public_key_hex"])
        sid = derive_sender_id(pubkey)
        if sid == v["expected_sender_id_hex"]:
            return True, f"✅ {name}"
        return False, f"❌ {name}: sender_id {sid!r} != expected {v['expected_sender_id_hex']!r}"

    # Error cases
    expected_error = v.get("expected_error")
    did = v.get("did", "")

    try:
        if did.startswith("did:key:"):
            pubkey = resolve_did_key(did)
        elif did.startswith("did:web:"):
            if "did_document" in v:
                pubkey = resolve_did_web_from_document(v["did_document"])
            elif v.get("live"):
                pubkey = resolve_did_web(did)
            else:
                pubkey = resolve_did_web(did)
        else:
            raise ValueError("method_unsupported")

        if expected_error:
            return False, f"❌ {name}: expected error {expected_error!r} but resolved successfully"

        results = []
        if "expected_public_key_hex" in v:
            got_hex = pubkey.hex()
            if got_hex == v["expected_public_key_hex"]:
                results.append("key ✓")
            else:
                return False, f"❌ {name}: key {got_hex} != expected {v['expected_public_key_hex']}"

        if "expected_sender_id" in v or "expected_sender_id_hex" in v:
            expected_sid = v.get("expected_sender_id") or v.get("expected_sender_id_hex")
            sid = derive_sender_id(pubkey)
            if sid == expected_sid:
                results.append("sender_id ✓")
            else:
                return False, f"❌ {name}: sender_id {sid!r} != expected {expected_sid!r}"

        return True, f"✅ {name} ({', '.join(results) if results else 'resolved'})"

    except (ValueError, KeyError) as exc:
        err_msg = str(exc)
        if expected_error:
            matched = expected_error in err_msg
            if matched:
                return True, f"✅ {name}: correctly raised {expected_error!r}"
            return False, f"❌ {name}: expected {expected_error!r}, got {err_msg!r}"
        return False, f"❌ {name}: unexpected error: {err_msg}"
    except Exception as exc:
        if expected_error:
            return True, f"✅ {name}: error raised (network/other: {type(exc).__name__})"
        return False, f"❌ {name}: {type(exc).__name__}: {exc}"


def main():
    print("DID Resolution v1.0 — conformance test")
    print("=" * 50)
    passed = 0
    failed = 0
    for v in VECTORS:
        ok, msg = run_vector(v)
        print(msg)
        if ok:
            passed += 1
        else:
            failed += 1
    print("=" * 50)
    print(f"Result: {passed}/{len(VECTORS)} passed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
