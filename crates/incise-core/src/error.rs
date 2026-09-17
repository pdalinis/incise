//! A failure whose message is handed straight back to a model.
//!
//! Not an error type in the usual Rust sense: the string *is* the product
//! (REQUIREMENTS.md §5.3). Arm B measured recovery rates against these exact
//! sentences — 75% of `op_error` trials recover in one extra turn — so the
//! wording is behaviour, not diagnostics, and `bench/incise_ops.py` is the
//! oracle for it byte-for-byte.

use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpError(pub String);

impl OpError {
    pub fn new(msg: impl Into<String>) -> Self {
        OpError(msg.into())
    }

    pub fn message(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for OpError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for OpError {}

pub type Result<T> = std::result::Result<T, OpError>;
