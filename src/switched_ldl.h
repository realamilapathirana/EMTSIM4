#pragma once

// Sparse LDL^T of G_UU for networks whose switching elements change a few entries at a time
// (Watson & Arrillaga section 9.3; the same idea as switched.py, in sparse form).
//
// - The nodes of switching and non-linear elements are ordered last: minimum degree among the
//   other nodes, then among them.
// - The ordering and the symbolic factorisation (elimination tree, column counts) are kept while
//   the sparsity pattern of G_UU stays the same; a switch changing between Ron and Roff changes
//   values only.
// - factor() compares the new values with the last ones. Row k of L and D(k) depend only on the
//   upper triangle of rows/columns <= k (up-looking factorisation), so only the rows from the first
//   one with a changed entry are recomputed; with the switched nodes last that is a few rows.

#include <cstddef>
#include <vector>

#include "linalg.h"

class SwitchedLDL {
public:
    // last[i] != 0: unknown node i belongs to a switching or non-linear element
    void setLast(std::vector<char> last) { last_ = std::move(last); }
    void factor(const SparseMatrix& A);    // throws if (numerically) singular
    Vector solve(const Vector& b) const;
    std::size_t nnzL() const { return Li_.size(); }

    int full = 0;          // ordering, symbolic and numeric factorisation
    int partial = 0;       // numeric from the first changed row
    int unchanged = 0;     // nothing to do
    std::size_t rowsRecomputed = 0;   // over all partial factorisations

private:
    void analyse(const SparseMatrix& A);
    void numeric(const SparseMatrix& A, std::size_t from);

    std::vector<char> last_;
    std::size_t n_ = 0;
    std::vector<std::size_t> Ap_, Ai_;   // pattern of the factorised matrix
    std::vector<double> Ax_;             // and its values
    std::vector<std::size_t> P_, Pinv_, parent_;
    std::vector<std::size_t> Lp_, Li_;
    std::vector<double> Lx_, D_;
};
