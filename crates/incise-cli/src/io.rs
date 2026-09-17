//! The file handling `incise-core` deliberately does not do.
//!
//! The core takes a `&str` and returns a `&str`, so everything that touches a
//! disk is here. REQUIREMENTS.md section 5.5 names three obligations and this
//! module is all three: the write is atomic, the bytes written are exactly the
//! bytes the op returned, and a content hash lets a caller say which version of
//! the file it meant.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

/// A fault in the call itself rather than in the edit: the file is missing, or
/// is not text, or could not be replaced. Distinct from an `OpError`, which is
/// a refusal the model is expected to recover from.
#[derive(Debug)]
pub struct IoFault(pub String);

pub fn read_bytes(path: &Path) -> Result<Vec<u8>, IoFault> {
    fs::read(path).map_err(|e| IoFault(format!("cannot read {}: {e}", path.display())))
}

/// The bytes as text, or a fault naming why they are not.
///
/// Encoding is unspecified everywhere in REQUIREMENTS.md, so the two cases it
/// leaves open are decided here and said out loud rather than absorbed:
///
/// * Not UTF-8: the core's signature cannot accept it at all.
/// * A leading U+FEFF: the core *would* accept it, as an ordinary character
///   sitting in front of the first `#`. The document would parse with no first
///   heading, every address into it would miss, and the refusal the model read
///   would be about a section that is plainly there. Section 5.5 says refuse and
///   explain rather than produce a plausible-but-wrong edit; a byte-order mark
///   in front of a heading is exactly that case.
///
/// Both are front-end refusals. `bench/incise_ops.py` has no opinion on either,
/// so neither is under differential test and neither pretends to be.
pub fn to_text(bytes: &[u8], path: &Path) -> Result<String, IoFault> {
    if bytes.starts_with(&[0xEF, 0xBB, 0xBF]) {
        return Err(IoFault(format!(
            "{} starts with a UTF-8 byte-order mark. incise addresses by content, \
             and a BOM sits in front of the first heading -- every address into this \
             file would miss. Strip it first: `tail -c +4`.",
            path.display()
        )));
    }
    String::from_utf8(bytes.to_vec())
        .map_err(|e| IoFault(format!("{} is not valid UTF-8: {e}", path.display())))
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(64);
    for b in Sha256::digest(bytes) {
        out.push_str(&format!("{b:02x}"));
    }
    out
}

/// Replace `path`'s contents with `data`, atomically.
///
/// Write to a sibling and rename, so a reader either sees the whole old file or
/// the whole new one. A partially-written markdown file is the failure section
/// 5.2 exists to prevent, and it is the one failure the op layer cannot prevent
/// on its own: byte-preserving splices are no help if the write is torn.
///
/// The temp file is a sibling and not in `/tmp` because `rename` is only atomic
/// within a filesystem. Permissions are copied from the original, since a fresh
/// file would otherwise take the umask's and silently narrow access to a file
/// that had been group-writable.
pub fn write_atomic(path: &Path, data: &str, expected: &[u8]) -> Result<(), IoFault> {
    let fault = |e: std::io::Error| IoFault(format!("cannot write {}: {e}", path.display()));

    // Renaming over a symlink replaces the link itself, not the file it names.
    // Resolve only that case so editing a linked note preserves the link and
    // updates the same target that `read_bytes` read.
    let target = match fs::symlink_metadata(path) {
        Ok(meta) if meta.file_type().is_symlink() => fs::canonicalize(path).map_err(fault)?,
        Ok(_) => path.to_path_buf(),
        Err(e) => return Err(fault(e)),
    };

    let dir = target
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let stem = target
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default();
    let temp: PathBuf = dir.join(format!(".{stem}.incise-{}.tmp", std::process::id()));

    let outcome = (|| {
        let mut f = fs::File::create(&temp)?;
        f.write_all(data.as_bytes())?;
        f.sync_all()?;
        drop(f);
        if let Ok(meta) = fs::metadata(&target) {
            // Best-effort: a filesystem that will not carry the mode is not a
            // reason to refuse the edit.
            let _ = fs::set_permissions(&temp, meta.permissions());
        }

        // The operation was derived from `expected`. Refuse an external write
        // that landed while Incise was computing rather than replacing it with
        // a stale result. This narrows the check-to-rename window to one local
        // read; same-process callers additionally serialize in integrations.
        if fs::read(&target)? != expected {
            return Err(std::io::Error::other(
                "the file changed after incise read it; re-read it and retry",
            ));
        }
        fs::rename(&temp, &target)
    })();

    if outcome.is_err() {
        let _ = fs::remove_file(&temp);
    }
    outcome.map_err(fault)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let n = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!("incise-io-{}-{n}-{name}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn the_hash_is_the_one_everything_else_agrees_with() {
        // FIPS 180-4 -- if this moves, every recorded `--if-match` moves with it.
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            sha256_hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn a_bom_is_refused_by_name() {
        let err = to_text("\u{feff}# Title\n".as_bytes(), Path::new("x.md"))
            .err()
            .unwrap();
        assert!(err.0.contains("byte-order mark"), "{}", err.0);
    }

    #[test]
    fn crlf_and_a_missing_final_newline_both_survive_to_text() {
        let raw = b"# A\r\n\r\ntext";
        assert_eq!(
            to_text(raw, Path::new("x.md")).ok().unwrap(),
            "# A\r\n\r\ntext"
        );
    }

    #[test]
    fn a_concurrent_change_is_not_overwritten() {
        let dir = scratch("stale");
        let path = dir.join("note.md");
        fs::write(&path, "original\n").unwrap();
        fs::write(&path, "external\n").unwrap();

        let err =
            write_atomic(&path, "incise\n", b"original\n").expect_err("a stale write must refuse");
        assert!(err.0.contains("changed after incise read it"), "{}", err.0);
        assert_eq!(fs::read_to_string(&path).unwrap(), "external\n");
        fs::remove_dir_all(dir).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn a_symlink_stays_a_symlink_and_its_target_changes() {
        use std::os::unix::fs::symlink;

        let dir = scratch("symlink");
        let target = dir.join("target.md");
        let link = dir.join("link.md");
        fs::write(&target, "before\n").unwrap();
        symlink(&target, &link).unwrap();

        write_atomic(&link, "after\n", b"before\n").unwrap();
        assert!(fs::symlink_metadata(&link)
            .unwrap()
            .file_type()
            .is_symlink());
        assert_eq!(fs::read_to_string(&target).unwrap(), "after\n");
        fs::remove_dir_all(dir).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn replacement_preserves_the_original_mode() {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};

        let dir = scratch("mode");
        let path = dir.join("note.md");
        fs::write(&path, "before\n").unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o640)).unwrap();

        write_atomic(&path, "after\n", b"before\n").unwrap();
        assert_eq!(fs::metadata(&path).unwrap().mode() & 0o777, 0o640);
        fs::remove_dir_all(dir).unwrap();
    }
}
