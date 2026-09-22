//! A failure whose message is handed straight back to a model.
//!
//! Not an error type in the usual Rust sense: the string *is* the product
//! (REQUIREMENTS.md §5.3). Arm B measured recovery rates against these exact
//! sentences — 75% of `op_error` trials recover in one extra turn — so the
//! wording is behaviour, not diagnostics, and `bench/incise_ops.py` is the
//! oracle for it byte-for-byte.

use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Repair {
    pub code: String,
    pub argument: Option<String>,
    pub received: Option<String>,
    pub candidates: Vec<String>,
    pub remedy: String,
}

impl Repair {
    pub fn new(code: impl Into<String>, remedy: impl Into<String>) -> Self {
        Repair {
            code: code.into(),
            argument: None,
            received: None,
            candidates: Vec::new(),
            remedy: remedy.into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpError(pub String, pub Option<Box<Repair>>);

impl OpError {
    pub fn new(msg: impl Into<String>) -> Self {
        OpError(msg.into(), None)
    }

    pub fn with_repair(msg: impl Into<String>, repair: Repair) -> Self {
        OpError(msg.into(), Some(Box::new(repair)))
    }

    pub fn message(&self) -> &str {
        &self.0
    }

    pub fn repair(&self) -> Option<&Repair> {
        self.1.as_deref()
    }
}

impl fmt::Display for OpError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for OpError {}

pub type Result<T> = std::result::Result<T, OpError>;
