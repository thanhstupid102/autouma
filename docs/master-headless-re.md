# Headless master.mdb update — RE findings (2026-07-21)

Goal: refresh `master.mdb` on a headless box (no game) after a game update, without launching the
game. Status: solved and proven end-to-end. The resource server and resource version from
`tool/start_session` are sufficient; the root-manifest URL no longer needs to be injected.

## Confirmed, proven facts

### CDN + resource server
- The API `tool/start_session` response gives everything needed to start:
  - `data_headers.server_list.resource_server` = `assets-umamusume-en.akamaized.net/dl/vertical/`
  - `data.resource_version` (res_ver), e.g. `10006910`.
- Content objects are served at:
  `https://assets-umamusume-en.akamaized.net/dl/vertical/resources/<Category>/<hname[:2]>/<hname>`
  where Category ∈ {`Generic`, `Manifest`, `Windows`} (path literals confirmed in
  global-metadata.dat: `resources/Generic/`, `resources/Manifest/`, `resources/Windows/`).
- Objects are PUBLIC (HTTP 200, no auth). Verified live: `Manifest/KA/KACB...` (200),
  `Manifest/YN/YNY6...` (200), `Generic/EH/EHI22...` (200).

### hname (content address) formula — for LEAF files
`hname = base32( sha1( uint64_be(checksum) ++ uint64_be(size) ++ utf8(name) ) )` (no `=` padding).
VERIFIED: name=`master.mdb.lz4`, checksum=264782442268972186, size=5010253
→ `EHI22T4Y3GBX52MTWGWBVIZK7OEKYWJ5` (exact match).
NOTE: manifest NODES (`//root`, `//Windows`, `//master`, `//<category>`) do NOT reproduce with this
formula — their hnames are stored by the parent manifest and read from it, not recomputed.

### Master payload — NO cipher
`master.mdb.lz4` is a plain LZ4 frame. Verified live: fetched `Generic/EH/EHI22...` (5,010,253 B) →
`lz4.frame.decompress` → 15,962,112 B starting with `SQLite format 3\0` = valid master.mdb. So the
headless path is just: fetch → lz4 decompress → write `master/master.mdb`. No decryption needed on
the master payload.

### Manifest chain structure (from the decrypted local `meta`)
`meta` (local manifest DB) decrypts to SQLite with tables `a` (191038 entries: i,n,d,g,l,c,h,m,k,s,
p,e), `c` (39 category→hname), `r` (deps), `i` (schema version 1.2). Chain:
- `//root`   (m=manifest3, k=3, checksum=0,size=0) h=`65D7AUVE3YRQDC4HDJGW3L47C27YALEW`
- `//Windows`(m=manifest2, k=2, 684 B)            h=`KACBMBBX5DCVMX4CB3WJCJDQWORBTXOA`
- `//master` (m=manifest,  k=1, 69 B)             h=`YNY6OBCCRJSYNSKQEBX75JB2L5HVJP4V`
- `master.mdb.lz4`(m=master,k=10, 5,010,253 B)    h=`EHI22T4Y3GBX52MTWGWBVIZK7OEKYWJ5`
`//Windows` content = the 39-category index (story, campaign, gacha, …, master, …) with each
category's hname. `//master` content = the `master.mdb.lz4` leaf entry (name+checksum+size).
Per-update, master.mdb changes → master.mdb.lz4 hname changes → //master hname changes → //Windows
hname changes → root content changes (root served at a versioned URL, see below).

### meta decryption (only needed to READ a LOCAL manifest DB, not for the CDN path)
`meta` is SQLite3MultipleCiphers, cipher type 3 (chacha20), raw key. Decrypt with the game's own
`UmamusumePrettyDerby_Data/Plugins/x86_64/libnative.dll` via ctypes:
`sqlite3_open_v2` → `sqlite3mc_config(db, "cipher", 3)` → `sqlite3_key(db, KEY, len)` then normal
queries. The working Global key was found by the reference project
`MarshmallowAndroid/UmamusumeExplorer` (keys list in `UmamusumeData/UmaDataHelper.cs`); it stores
an ASCII passphrase key that verified (integrity_check ok). The CDN Manifest objects are LZ4 BSV
(NOT chacha20) — so a from-scratch CDN walk does NOT need meta decryption at all; meta decryption is
only a convenience for inspecting the current install.

## Recovered versioned root-manifest URL

The exact client-equivalent construction is:

```python
root_url = (
    f"{base.rstrip('/')}/{res_ver}/manifests/manifestdat/"
    f"root.manifest.bsv.lz4?r={int(time.time())}"
)
```

`base` is the normalized `server_list.resource_server` including `https://`; `?r=` is the current
UTC Unix timestamp in seconds and is only a cache buster. It is not `res_ver`, a formatted date, or
the unrelated `2050/01/01` literal.

### Live disassembly and literal evidence

The module base was re-read from the running process as `0x7ffb2d7e0000`; no address from the
sidecar was assumed. At `GetDirectRootManifestUrl` RVA `0x045319e0`:

- `0x045319f1: mov rdi, rcx` preserves the `resourceVersion` argument.
- Literal-cache global RVA `0x06bcce40` held `Il2CppString* 0x1b2f30152a0`, whose length at `+0x10`
  and UTF-16 data at `+0x14` read `https://`.
- Literal-cache global RVA `0x06c23958` held `Il2CppString* 0x1b2f3019b40`, which read
  `/manifests/manifestdat/` by the same layout.
- The `Gallop.GameDefine` TypeInfo global at RVA `0x06ca0a90` led through `klass + 0xb8` (static
  fields) and `static_fields + 0xc8` to `_receivedResourceServerForManifest`, an
  `ObscuredString`. Reading its live key and UTF-16 encrypted words and applying the class's XOR
  transform produced `assets-umamusume-en.akamaized.net/dl/vertical/`.
- Immediately before the four-string concat at RVA `0x04531bcb`, the registers are
  `rcx="https://"`, `rdx=<decrypted manifest server>`, `r8=rdi` (resource version), and
  `r9="/manifests/manifestdat/"`. Therefore this function returns
  `https://assets-umamusume-en.akamaized.net/dl/vertical/<res_ver>/manifests/manifestdat/`.

The oversized dump also contains `2050/01/01`, but it is referenced by the neighboring class
initializer, not by `GetDirectRootManifestUrl`. The fallback resource-server getters share the
still-uninitialized global value `0xa000e0d9` (there is no `Il2CppString*` until that unused branch's
runtime-metadata initializer runs). Decoding its usage index as `0x706c` against the live-mapped
metadata at `0x1b1a0ae0000` led to entry `0x1b1a0b18460`; its live length/data-index pair read the
compile-time placeholder `https://xxxxxxxxxx/dl/`. It is not selected after `start_session`
populates the three received-server fields; all three live `ObscuredString` payloads decoded to the
same Akamai host/path. `GetManifestUrl` independently uses that live manifest server with the
literal `resources/Manifest/`, confirming the content-store base.

Cyan completes the URL after `GameDefine` supplies the directory:

- `PathResolver.SetDirectRootManifestUrl` at RVA `0x05931b30` calls `String.TrimHelper` with `/` and
  trims the directory's trailing slash.
- `ManifestSynchronizer.SychronizeManifestDB` loads the literal
  `/root.manifest.bsv.lz4?r=`. Its call sequence is `DateTime.UtcNow` (RVA `0x01e8e690`) →
  `DateTimeOffset(DateTime)` (`0x01e8ea20`) → `ToUnixTimeSeconds` (`0x01e90da0`) →
  `Int64.ToString` (`0x01eae110`), followed by a three-string concat with the trimmed directory.
- Native request buffers from the same live process retained
  `10006910/manifests/manifestdat/root.manifest.bsv.lz4?r=1784567700` and a later request with
  `?r=1784567885`. A managed `System.String` object independently read `10006910`, confirming the
  live resource version.

### Live HTTPS validation

Using `res_ver=10006910` and the then-current cache-buster `1784569087`, the reconstructed URL
returned HTTP 200 with a 77-byte LZ4 frame. Decompression produced a 62-byte Cyan BSV with schema
`0318200340122108`; its first row decoded as:

`//Windows`, size `684`, checksum `7148908050129452712`, hname
`KACBMBBX5DCVMX4CB3WJCJDQWORBTXOA`.

That exactly matches the current known chain. The updater accepts this live root schema as the same
simplified `(name, size, checksum)` layout as the older `2518200340122108` variant, then follows the
already-proven Manifest → Manifest → Generic chain and validates SQLite before replacement.

A live `fetch_master_mdb(..., root_url=None, dry_run=True)` then exercised that default end-to-end:
`KACBM...` → `YNY6...` → `EHI22...`, 5,010,253 compressed bytes → 15,962,112-byte SQLite,
`PRAGMA integrity_check = ok`, and `replaced=False`.

## Reference
`MarshmallowAndroid/UmamusumeExplorer` (cloned during RE): reads the local encrypted `meta`/`master`
with SQLite3MultipleCiphers chacha20; does NOT download from CDN (so the CDN walk above is new work,
but the crypto + data-layout confirmations came from it).
