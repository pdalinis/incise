//! One module per op family, in the build order §11 ranked by measured harm.
//!
//! Tables first because they are where the corruption was measured; lists and
//! sections follow (Tier 2b and 2c), and frontmatter last, which is the order
//! `bench/incise_ops.py` was written in too.

pub mod dispatch;
pub mod frontmatter;
pub mod list;
pub mod section;
pub mod table;
