"""Factorisation of G_UU for networks whose switching elements change a few entries at a time
(Watson & Arrillaga section 9.3; the same idea as src/switched_ldl.cpp, in dense form).

The nodes of switching and non-linear elements (S) are ordered after all the others (N):

    G_UU = [[A, B],      A = G[N, N] does not change when an element switches, so it is
            [C, D]]      factorised once, with X = A^-1 B; a switching only refactorises the
                         Schur complement D - C X of the switched nodes.

factor() compares the new matrix with the last one: when A, B and C are unchanged (a switch,
a diode, a non-linear segment) only the Schur complement is refactorised; when they changed
(root matching's half steps change every R-L branch) everything is; when nothing changed,
nothing is. With fewer than SMALL other nodes the blocks cost more than they save (numpy calls
per step), so one plain LU is used, still skipped when nothing changed."""
import numpy as np
import scipy.linalg as la

SMALL = 200


class SwitchedLU:
    def __init__(self, n, last):
        """n unknown nodes; last: indices of the nodes of switching elements"""
        last = set(last)
        self.S = np.array(sorted(last), dtype=int)
        self.N = np.array([i for i in range(n) if i not in last], dtype=int)
        self.plain = len(self.N) < SMALL or not len(self.S)
        self.blocks = None          # A, B, C, D of the last factorisation (plain: the matrix)
        self.full = self.partial = self.unchanged = 0

    def factor(self, G):
        if self.plain:
            if self.blocks is not None and np.array_equal(G, self.blocks):
                self.unchanged += 1
                return
            self.full += 1
            self.lu = la.lu_factor(G)
            self.blocks = G.copy()
            return
        N, S = self.N, self.S
        A, B, C, D = G[np.ix_(N, N)], G[np.ix_(N, S)], G[np.ix_(S, N)], G[np.ix_(S, S)]
        old = self.blocks
        if old is not None and all(np.array_equal(x, y) for x, y in zip((A, B, C), old[:3])):
            if np.array_equal(D, old[3]):
                self.unchanged += 1
                return
            self.partial += 1
        else:
            self.full += 1
            self.luA = la.lu_factor(A) if len(N) else None
            self.X = la.lu_solve(self.luA, B) if len(N) and len(S) else np.zeros((len(N), len(S)))
        self.luS = la.lu_factor(D - C @ self.X) if len(S) else None
        self.blocks = (A.copy(), B.copy(), C.copy(), D.copy())

    def solve(self, b):
        """x with G_UU x = b (b: a vector or a column)"""
        if self.plain:
            return la.lu_solve(self.lu, b)
        N, S = self.N, self.S
        x = np.empty_like(b, dtype=float)
        y = la.lu_solve(self.luA, b[N]) if len(N) else b[N]
        if len(S):
            C = self.blocks[2]
            xs = la.lu_solve(self.luS, b[S] - C @ y)
            x[S] = xs
            x[N] = y - self.X @ xs
        else:
            x[N] = y
        return x
