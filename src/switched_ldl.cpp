#include "switched_ldl.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>
#include <stdexcept>

namespace {

constexpr std::size_t NONE = std::numeric_limits<std::size_t>::max();

// Minimum degree on the graph of a symmetric matrix (as minimumDegreeOrder in linalg.cpp), except
// that a node with last[] set is eliminated only after all the others.
std::vector<std::size_t> orderSwitchedLast(const SparseMatrix& A, const std::vector<char>& last) {
    const std::size_t n = A.cols();
    const auto& Ap = A.colptr();
    const auto& Ai = A.rowind();
    std::vector<std::set<std::size_t>> g(n);
    for (std::size_t j = 0; j < n; ++j)
        for (std::size_t p = Ap[j]; p < Ap[j + 1]; ++p)
            if (Ai[p] != j) { g[Ai[p]].insert(j); g[j].insert(Ai[p]); }
    const auto isLast = [&](std::size_t k) { return k < last.size() && last[k]; };

    std::vector<char> done(n, 0);
    std::vector<std::size_t> order;
    order.reserve(n);
    for (std::size_t step = 0; step < n; ++step) {
        std::size_t v = NONE, best = NONE;
        bool bestLast = true;
        for (std::size_t k = 0; k < n; ++k) {
            if (done[k]) continue;
            const bool l = isLast(k);
            if (v == NONE || (bestLast && !l) || (l == bestLast && g[k].size() < best)) {
                v = k; best = g[k].size(); bestLast = l;
            }
        }
        order.push_back(v);
        done[v] = 1;
        const std::vector<std::size_t> nb(g[v].begin(), g[v].end());
        for (std::size_t a : nb) g[a].erase(v);
        for (std::size_t x = 0; x < nb.size(); ++x)
            for (std::size_t y = x + 1; y < nb.size(); ++y) { g[nb[x]].insert(nb[y]); g[nb[y]].insert(nb[x]); }
        g[v].clear();
    }
    return order;
}

}  // namespace

void SwitchedLDL::analyse(const SparseMatrix& A) {
    n_ = A.cols();
    Ap_ = A.colptr();
    Ai_ = A.rowind();
    P_ = orderSwitchedLast(A, last_);
    Pinv_.assign(n_, 0);
    for (std::size_t k = 0; k < n_; ++k) Pinv_[P_[k]] = k;

    // elimination tree and the number of non-zeros in each column of L (upper triangle of P A P^T)
    parent_.assign(n_, NONE);
    std::vector<std::size_t> flag(n_), lnz(n_, 0);
    for (std::size_t k = 0; k < n_; ++k) {
        flag[k] = k;
        const std::size_t kk = P_[k];
        for (std::size_t p = Ap_[kk]; p < Ap_[kk + 1]; ++p) {
            std::size_t i = Pinv_[Ai_[p]];
            if (i >= k) continue;
            for (; flag[i] != k; i = parent_[i]) {
                if (parent_[i] == NONE) parent_[i] = k;
                ++lnz[i];
                flag[i] = k;
            }
        }
    }
    Lp_.assign(n_ + 1, 0);
    for (std::size_t k = 0; k < n_; ++k) Lp_[k + 1] = Lp_[k] + lnz[k];
    Li_.assign(Lp_[n_], 0);
    Lx_.assign(Lp_[n_], 0.0);
    D_.assign(n_, 0.0);
}

void SwitchedLDL::numeric(const SparseMatrix& A, std::size_t from) {
    const auto& Ax = A.val();
    // Columns of L are filled in increasing row order, so the entries of rows < from are the
    // first ones of each column: keep them, recompute the rest.
    std::vector<std::size_t> lnz(n_, 0), flag(n_, NONE), pattern(n_);
    for (std::size_t i = 0; i < std::min(from, n_); ++i)
        lnz[i] = static_cast<std::size_t>(std::lower_bound(Li_.begin() + Lp_[i], Li_.begin() + Lp_[i + 1], from) -
                                          (Li_.begin() + Lp_[i]));
    Vector Y(n_, 0.0);
    for (std::size_t k = from; k < n_; ++k) {   // row k of L and D(k) from rows 0..k-1 (up-looking)
        std::size_t top = n_;
        flag[k] = k;
        double akk = 0.0;
        const std::size_t kk = P_[k];
        for (std::size_t p = Ap_[kk]; p < Ap_[kk + 1]; ++p) {
            std::size_t i = Pinv_[Ai_[p]];
            if (i > k) continue;
            Y[i] += Ax[p];
            if (i == k) akk += Ax[p];
            std::size_t len = 0;
            for (; flag[i] != k; i = parent_[i]) {
                pattern[len++] = i;
                flag[i] = k;
            }
            while (len > 0) pattern[--top] = pattern[--len];
        }
        D_[k] = Y[k];
        Y[k] = 0.0;
        for (; top < n_; ++top) {
            const std::size_t i = pattern[top];
            const double yi = Y[i];
            Y[i] = 0.0;
            const std::size_t p2 = Lp_[i] + lnz[i];
            for (std::size_t p = Lp_[i]; p < p2; ++p) Y[Li_[p]] -= Lx_[p] * yi;
            const double lki = yi / D_[i];
            D_[k] -= lki * yi;
            Li_[p2] = k;
            Lx_[p2] = lki;
            ++lnz[i];
        }
        if (!(std::fabs(D_[k]) > 1e-13 * std::fabs(akk)) || D_[k] == 0.0)
            throw std::runtime_error("Sparse LDL: conductance matrix is singular (is there a floating node?)");
    }
    Ax_ = Ax;
}

void SwitchedLDL::factor(const SparseMatrix& A) {
    if (A.rows() != A.cols()) throw std::invalid_argument("SwitchedLDL: matrix must be square");
    if (Ap_.empty() || A.cols() != n_ || A.colptr() != Ap_ || A.rowind() != Ai_) {
        analyse(A);
        numeric(A, 0);
        ++full;
        return;
    }
    // first row of L that sees a changed entry: entry (r, c) is used from row max(Pinv r, Pinv c)
    const auto& Ax = A.val();
    std::size_t from = n_;
    for (std::size_t j = 0; j < n_; ++j)
        for (std::size_t p = Ap_[j]; p < Ap_[j + 1]; ++p)
            if (Ax[p] != Ax_[p]) from = std::min(from, std::max(Pinv_[Ai_[p]], Pinv_[j]));
    if (from == n_) {
        ++unchanged;
        return;
    }
    numeric(A, from);
    ++partial;
    rowsRecomputed += n_ - from;
}

Vector SwitchedLDL::solve(const Vector& b) const {
    if (b.size() != n_) throw std::invalid_argument("SwitchedLDL solve: size mismatch");
    Vector x(n_);
    for (std::size_t k = 0; k < n_; ++k) x[k] = b[P_[k]];         // x = P b
    for (std::size_t j = 0; j < n_; ++j)                           // L y = P b
        for (std::size_t p = Lp_[j]; p < Lp_[j + 1]; ++p) x[Li_[p]] -= Lx_[p] * x[j];
    for (std::size_t j = 0; j < n_; ++j) x[j] /= D_[j];            // D z = y
    for (std::size_t j = n_; j-- > 0;)                             // L^T w = z
        for (std::size_t p = Lp_[j]; p < Lp_[j + 1]; ++p) x[j] -= Lx_[p] * x[Li_[p]];
    Vector out(n_);
    for (std::size_t k = 0; k < n_; ++k) out[P_[k]] = x[k];       // x = P^T w
    return out;
}
