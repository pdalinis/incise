//! Python `difflib`, ported: close-match ranking and the opcode-level diff.
//!
//! Every "Near matches:" line in an error message comes from
//! `difflib.get_close_matches`, so a Rust implementation that ranks candidates
//! differently produces a different *message*, and the message is what the
//! benchmark measured (§5.3). This is therefore a port of the algorithm, not a
//! substitute for it: `SequenceMatcher` with the same matching-block recursion
//! and the same tie-breaking.
//!
//! **One deliberate divergence, and only one: there is no autojunk.** difflib
//! drops elements occurring more than `len(b) / 100 + 1` times once `b` reaches
//! 200, on the assumption that popular elements are noise. For both callers
//! here they are the signal — the blank lines and table delimiters a line diff
//! anchors on, and the spaces and vowels of a sentence-length cell value. The
//! oracle diverges in the same place and for the same reason
//! (`bench/incise_ops.py`'s `_close_matches` and `_line_counts`), so the two
//! implementations still agree; `bench/FINDINGS.md` F-autojunk and F-nearmatch
//! are the measurements that say the divergence is right, and
//! `bench/test_incise_ops.py` pins the oracle to stdlib everywhere the
//! heuristic could not have engaged anyway.
//!
//! Three simplifications that are provably equivalent rather than convenient:
//!
//! * `get_close_matches` filters on `real_quick_ratio` and `quick_ratio`
//!   before `ratio`. Both are upper bounds on `ratio`, so filtering on `ratio`
//!   alone selects the identical set — they exist to skip work, not to change
//!   the answer.
//! * `heapq.nlargest` decorates with a descending counter, which makes it
//!   stable for fully-equal entries; a stable sort on the same key is the same
//!   ordering. Ties on score are broken by the candidate string *descending*,
//!   because Python is comparing `(score, x)` tuples.
//! * difflib runs four extension loops after the DP in `find_longest_match`.
//!   All four are dead without junk: two are guarded by `isbjunk` on an empty
//!   set, and the other two can only fire on a match the DP failed to find,
//!   which an unpurged index makes impossible. See [`Matcher::longest_match`].
//!
//! [`Matcher`] is generic over the element type because the two callers compare
//! different things: `get_close_matches` diffs a heading path against a
//! candidate *by character*, and [`crate::describe`] diffs one document against
//! another by heading text and by line. The b-side index is the expensive half,
//! so it is built once per `b` and reused across every `a`.

use std::collections::HashMap;
use std::hash::Hash;

/// `difflib.get_close_matches(word, possibilities, n, cutoff)`.
pub fn get_close_matches(
    word: &str,
    possibilities: &[String],
    n: usize,
    cutoff: f64,
) -> Vec<String> {
    let b: Vec<char> = word.chars().collect();
    let matcher = Matcher::new(&b);
    let mut scored: Vec<(f64, &String)> = Vec::new();
    for cand in possibilities {
        let a: Vec<char> = cand.chars().collect();
        let r = matcher.ratio(&a);
        if r >= cutoff {
            scored.push((r, cand));
        }
    }
    // Stable sort descending by (score, string) — the tuple comparison Python's
    // heap does. `partial_cmp` cannot fail here: `ratio` is finite by
    // construction (a non-negative sum over a positive total).
    scored.sort_by(|x, y| {
        y.0.partial_cmp(&x.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| y.1.cmp(x.1))
    });
    scored.into_iter().take(n).map(|(_, s)| s.clone()).collect()
}

/// One entry of `SequenceMatcher.get_opcodes()`: what to do with `a[i1..i2]`
/// to turn it into `b[j1..j2]`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tag {
    Replace,
    Delete,
    Insert,
    Equal,
}

/// `SequenceMatcher` with `b` fixed, which is how both callers use it:
/// `set_seq2(b)` once, then `set_seq1(a)` per comparison. The b-side index is
/// the expensive half, so building it once is the point.
pub struct Matcher<'a, T: Eq + Hash> {
    b: &'a [T],
    b2j: HashMap<&'a T, Vec<usize>>,
}

impl<'a, T: Eq + Hash> Matcher<'a, T> {
    /// `SequenceMatcher(None, a, b, autojunk=False)`.
    ///
    /// There is no autojunk-on constructor, because nothing wants one. The
    /// heuristic purges elements appearing in more than 1% of a long `b`, and
    /// both callers need exactly those: [`crate::describe`] diffs a document's
    /// line list, where the popular elements are the blank line and the table
    /// delimiter — keeping it there reported an 18-line delete as
    /// `(+71 lines, -89 lines)` — and [`get_close_matches`] diffs a value's
    /// *characters*, where a 200-character cell value loses its spaces and
    /// vowels and stops being compared as a string at all.
    ///
    /// Removing it is what makes the four extension loops in `longest_match`
    /// dead rather than merely unreached; the two facts are one fact, and the
    /// note there is the other half of this one. `bench/FINDINGS.md`
    /// F-autojunk and F-nearmatch.
    pub fn new(b: &'a [T]) -> Self {
        let mut b2j: HashMap<&'a T, Vec<usize>> = HashMap::new();
        for (i, elt) in b.iter().enumerate() {
            b2j.entry(elt).or_default().push(i);
        }
        Matcher { b, b2j }
    }

    /// `2 * M / T`, where M is the total size of the matching blocks.
    pub fn ratio(&self, a: &[T]) -> f64 {
        let total = a.len() + self.b.len();
        if total == 0 {
            return 1.0;
        }
        2.0 * self.matches(a) as f64 / total as f64
    }

    /// The sum of `get_matching_blocks()` sizes.
    ///
    /// Computed from the blocks themselves rather than by a cheaper parallel
    /// recursion. An earlier version summed sizes without the merge or the
    /// sort, on the argument that neither changes the total — true, but it left
    /// two code paths where one of them was reachable only by `ratio` and so
    /// was the only one anybody checked. One path, one set of bugs.
    pub fn matches(&self, a: &[T]) -> usize {
        self.matching_blocks(a).iter().map(|&(_, _, k)| k).sum()
    }

    /// `get_matching_blocks()`: monotonically increasing, non-adjacent, and
    /// terminated by the `(len(a), len(b), 0)` sentinel.
    ///
    /// The queue is LIFO, so blocks come out unordered and Python sorts them.
    /// Dropping the sort changes the *opcodes* while leaving the size total
    /// alone, which is why `matches` above is not evidence that this is right.
    ///
    /// The collapse afterwards is carried for fidelity and **cannot fire here**.
    /// Two blocks abut only when `a[i-1] == b[j-1]` at the second one's start,
    /// and the first block is the longest run in a region that reaches to
    /// `(i-1, j-1)` — so that equality would have made it one element longer,
    /// and `longest_match` would have returned the longer run. Python needs the
    /// pass because `isjunk` splits matches and its extension loops decline to
    /// rejoin them; this port has no `isjunk` and no purge, so it has neither
    /// the split nor the loops.
    ///
    /// It therefore has no mutation either (`bench/FINDINGS.md` F-extend), and
    /// that is the same fact once more: with a complete index the DP's
    /// maximality does all of this work, which is why the collapse is dead here
    /// and why the extension loops are too. Note the argument now rests on the
    /// DP rather than on those loops — before F-nearmatch it was phrased the
    /// other way round, and removing them would have quietly invalidated it.
    pub fn matching_blocks(&self, a: &[T]) -> Vec<(usize, usize, usize)> {
        let (la, lb) = (a.len(), self.b.len());
        let mut queue = vec![(0usize, la, 0usize, lb)];
        let mut blocks: Vec<(usize, usize, usize)> = Vec::new();
        while let Some((alo, ahi, blo, bhi)) = queue.pop() {
            let (i, j, k) = self.longest_match(a, alo, ahi, blo, bhi);
            if k == 0 {
                continue;
            }
            blocks.push((i, j, k));
            if alo < i && blo < j {
                queue.push((alo, i, blo, j));
            }
            if i + k < ahi && j + k < bhi {
                queue.push((i + k, ahi, j + k, bhi));
            }
        }
        blocks.sort_unstable();

        let (mut i1, mut j1, mut k1) = (0usize, 0usize, 0usize);
        let mut out: Vec<(usize, usize, usize)> = Vec::new();
        for (i2, j2, k2) in blocks {
            if i1 + k1 == i2 && j1 + k1 == j2 {
                k1 += k2;
            } else {
                if k1 > 0 {
                    out.push((i1, j1, k1));
                }
                i1 = i2;
                j1 = j2;
                k1 = k2;
            }
        }
        if k1 > 0 {
            out.push((i1, j1, k1));
        }
        out.push((la, lb, 0));
        out
    }

    /// `get_opcodes()`.
    pub fn opcodes(&self, a: &[T]) -> Vec<(Tag, usize, usize, usize, usize)> {
        let (mut i, mut j) = (0usize, 0usize);
        let mut answer = Vec::new();
        for (ai, bj, size) in self.matching_blocks(a) {
            let tag = if i < ai && j < bj {
                Some(Tag::Replace)
            } else if i < ai {
                Some(Tag::Delete)
            } else if j < bj {
                Some(Tag::Insert)
            } else {
                None
            };
            if let Some(t) = tag {
                answer.push((t, i, ai, j, bj));
            }
            i = ai + size;
            j = bj + size;
            if size > 0 {
                answer.push((Tag::Equal, ai, i, bj, j));
            }
        }
        answer
    }

    /// `find_longest_match`, including its bias toward the earliest match.
    ///
    /// difflib runs four `while` loops after the DP. The **second pair**
    /// extends the match over elements that *are* junk and is unreachable with
    /// an empty `bjunk`, which is the whole of this port. The **first pair**
    /// extends it over elements that are not, and is guarded by
    /// `not isbjunk(...)` — always true when the set is empty — so it runs on
    /// every call in difflib. It is still omitted here, but for a reason that
    /// had to be earned rather than assumed, because omitting it on the wrong
    /// reason is exactly what F-extend found.
    ///
    /// **The loops can only fire on a match the DP failed to find, and the DP
    /// fails only when the index is incomplete.** `j2len` carries, for each
    /// `j`, the length of the run ending at `(i, j)`; every matching pair is
    /// visited, so the longest run in `alo..ahi × blo..bhi` is found exactly.
    /// A left extension needs `a[besti-1] == b[bestj-1]`, which would mean a
    /// strictly longer run ending at the same `(i, j)` — and the DP would have
    /// recorded that instead. The right extension is the same argument at the
    /// other end. Both loops are within the same region bounds as the DP, so
    /// there is no gap for them to cover.
    ///
    /// The premise is "the index is complete", and it is [`Matcher::new`] that
    /// supplies it: with autojunk gone, nothing is ever purged. difflib needs
    /// the loops precisely because it purges; this port does not have them
    /// because it does not. An earlier version of this file omitted the loops
    /// *while* purging, which is the one combination that is wrong — it
    /// reported a matching total of 120 where Python reported 240 — and the
    /// comment justifying it confused `bpopular` with `bjunk`. `__chain_b`
    /// keeps the two sets apart; so does this note.
    fn longest_match(
        &self,
        a: &[T],
        alo: usize,
        ahi: usize,
        blo: usize,
        bhi: usize,
    ) -> (usize, usize, usize) {
        let (mut besti, mut bestj, mut bestsize) = (alo, blo, 0usize);
        let mut j2len: HashMap<usize, usize> = HashMap::new();
        for (i, item) in a.iter().enumerate().take(ahi).skip(alo) {
            let mut newj2len: HashMap<usize, usize> = HashMap::new();
            if let Some(idxs) = self.b2j.get(item) {
                for &j in idxs {
                    if j < blo {
                        continue;
                    }
                    if j >= bhi {
                        break;
                    }
                    let k = j
                        .checked_sub(1)
                        .and_then(|jm| j2len.get(&jm).copied())
                        .unwrap_or(0)
                        + 1;
                    newj2len.insert(j, k);
                    if k > bestsize {
                        besti = i + 1 - k;
                        bestj = j + 1 - k;
                        bestsize = k;
                    }
                }
            }
            j2len = newj2len;
        }
        (besti, bestj, bestsize)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(xs: &[&str]) -> Vec<String> {
        xs.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn matches_the_documented_difflib_example() {
        // From the difflib docs, which is the only fixed point this port has
        // that does not come from our own corpus.
        let words = v(&["ape", "apple", "peach", "puppy"]);
        assert_eq!(
            get_close_matches("appel", &words, 3, 0.6),
            v(&["apple", "ape"])
        );
    }

    #[test]
    fn cutoff_excludes_and_n_truncates() {
        let cols = v(&["Component", "Status", "Owner"]);
        assert_eq!(
            get_close_matches("Componant", &cols, 2, 0.4),
            v(&["Component"])
        );
        assert!(get_close_matches("zzzzzz", &cols, 2, 0.4).is_empty());
    }

    #[test]
    fn ties_break_on_the_string_descending() {
        // Both score identically against "b"; Python compares the tuples, so
        // the lexicographically larger candidate comes first.
        let words = v(&["ab", "cb"]);
        assert_eq!(get_close_matches("b", &words, 2, 0.4), v(&["cb", "ab"]));
    }

    fn chars(s: &str) -> Vec<char> {
        s.chars().collect()
    }

    #[test]
    fn matching_blocks_match_the_documented_difflib_example() {
        // >>> SequenceMatcher(None, "abxcd", "abcd").get_matching_blocks()
        // [Match(a=0, b=0, size=2), Match(a=3, b=2, size=2), Match(a=5, b=4, size=0)]
        let (a, b) = (chars("abxcd"), chars("abcd"));
        assert_eq!(
            Matcher::new(&b).matching_blocks(&a),
            vec![(0, 0, 2), (3, 2, 2), (5, 4, 0)]
        );
    }

    #[test]
    fn opcodes_match_the_documented_difflib_example() {
        // The worked example in `get_opcodes`' own docstring.
        let (a, b) = (chars("qabxcd"), chars("abycdf"));
        assert_eq!(
            Matcher::new(&b).opcodes(&a),
            vec![
                (Tag::Delete, 0, 1, 0, 0),
                (Tag::Equal, 1, 3, 0, 2),
                (Tag::Replace, 3, 4, 2, 3),
                (Tag::Equal, 4, 6, 3, 5),
                (Tag::Insert, 6, 6, 5, 6),
            ]
        );
    }

    #[test]
    fn a_complete_index_needs_no_extension_loops() {
        // The regression this module's history is about, kept as the test that
        // would catch its return. difflib purges popular elements once `b`
        // reaches 200 and then needs four extension loops to match back through
        // them; this port purges nothing and has no loops, and the two have to
        // stay in step. A long `b` full of one popular element (the blank line,
        // 120 of 241) is where a reintroduced purge would show first: Python
        // with `autojunk=False` reports 240 here, and the old
        // purge-without-loops combination reported 120.
        let lines: Vec<String> = (0..120)
            .flat_map(|i| [format!("line {i}"), String::new()])
            .collect();
        let mut after = lines.clone();
        after.insert(50, "INSERTED".to_string());
        assert!(
            after.len() >= 200,
            "the fixture must cross difflib's autojunk boundary"
        );

        let m = Matcher::new(&after);
        assert_eq!(m.matches(&lines), lines.len());

        // Same shape, comfortably under the threshold, where difflib would not
        // have purged either: the answer must not depend on which side of 200
        // the input falls, which is the property autojunk breaks.
        let short: Vec<String> = (0..20)
            .flat_map(|i| [format!("line {i}"), String::new()])
            .collect();
        let mut short_after = short.clone();
        short_after.insert(10, "INSERTED".to_string());
        assert!(short_after.len() < 200);
        assert_eq!(Matcher::new(&short_after).matches(&short), short.len());
    }

    #[test]
    fn a_long_value_still_finds_its_near_match() {
        // F-nearmatch, as a fixed point. `b` is the *word*, so a 200-character
        // value is what engages difflib's heuristic -- and with it engaged this
        // returned nothing at all, because the characters it purges from a
        // sentence are the spaces and the vowels.
        let cell = "Returning the heading outline alongside the one-line description was \
                    statistically identical to returning the outline alone, so the omission \
                    is the deliverable and the sentence on its own is what the measurement \
                    actually adopted here.";
        assert!(cell.len() >= 200, "the fixture must cross the boundary");
        let probe = cell.replacen("Returning ", "", 1);
        let got = get_close_matches(&probe, &[cell.to_string()], 3, 0.4);
        assert_eq!(got, vec![cell.to_string()]);
    }

    #[test]
    fn opcodes_always_reconstruct_b_from_a() {
        let (a, b) = (chars("the quick brown fox"), chars("a quick red fox jumps"));
        let m = Matcher::new(&b);
        let mut rebuilt = Vec::new();
        for (tag, i1, i2, j1, j2) in m.opcodes(&a) {
            match tag {
                Tag::Equal => rebuilt.extend_from_slice(&a[i1..i2]),
                Tag::Replace | Tag::Insert => rebuilt.extend_from_slice(&b[j1..j2]),
                Tag::Delete => {}
            }
        }
        assert_eq!(rebuilt, b);
    }
}
