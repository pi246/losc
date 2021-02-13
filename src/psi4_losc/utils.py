import psi4
import numpy as np


def form_df_basis_matrix(wfn):
    """
    Form the three-center integral used in density fitting.

    Parameters
    ----------
    wfn: psi4.core.wavefunction
        A psi4 wavefunction object.

    Returns
    -------
    df_pmn: np.array [nfitbasis, nbasis x nbasis]
        The three-center integral of <fitbasis|basis, basis>.
    df_Vpq_inv: np.array [nfitbasis, nfitbasis]
        The inverse of matrix <fitbasis|1/r|fitbasis>.
    """
    # basis set
    basis = wfn.basisset()
    zero_bas = psi4.core.BasisSet.zero_ao_basis_set()
    aux_bas_name = psi4.core.get_global_option('DF_BASIS_SCF').lower()
    aux_bas = psi4.core.BasisSet.build(wfn.molecule(), "ORBITAL", aux_bas_name)
    aux_bas.print_out()
    # psi4.mintshelper object to help building AO integrals.
    mints = psi4.core.MintsHelper(basis)
    # build three-center integral <fitbasis|ao, ao>
    df_pmn = np.asarray(mints.ao_eri(aux_bas, zero_bas, basis, basis))
    df_pmn = np.squeeze(df_pmn)
    # build density fitting Vpq inverse
    df_Vpq = np.asarray(mints.ao_eri(aux_bas, zero_bas, aux_bas, zero_bas))
    df_Vpq = np.squeeze(df_Vpq)
    df_Vpq_inv = np.linalg.inv(df_Vpq)

    return df_pmn, df_Vpq_inv


def form_grid_lo(wfn, C_lo):
    """
    Form the matrix that stores the values of LOs on grid points.

    Parameters
    ----------
    wfn: psi4.core.HF
        A psi4 HF object that is associated with a DFT calculations.
    C_lo: np.array [nbasis, nlo]
        LO coefficient matrix on AOs.

    Returns
    -------
    grid_lo: np.array [npts, nlo]
        A matrix for the values of LOs on grid points. npts is the number of
        grid points, and nlo is the number of LOs.
    """
    if not isinstance(wfn, psi4.core.HF):
        raise Exception("Unknown type of argument wfn. It has to be the type of psi4.core.HF.")
    # psi4.VBase object to help building grid.
    Vpot = wfn.V_potential()
    # number of grid points
    npts = Vpot.grid().npoints()
    # number of LOs.
    nlo = C_lo.shape[1]
    # Get the psi4.potential object for help
    # Note:
    # Vpot.properties() returns `nthread` number of pointer functions
    # (psi4 core object). These multiple pointer functions work in parallel
    # in psi4 core.
    # Here, we work in the python layer and do not use parallel construction
    # of grid yet. So we always use the first pointer function object to
    # build grid.
    points_func = Vpot.properties()[0]

    # allocate grid_lo matrices.
    grid_lo = np.zeros((npts, nlo))

    # loop over the blocks to build grid_lo
    npts_count = 0
    for b in range(Vpot.nblocks()):
        # Obtain block information
        block = Vpot.get_block(b)
        points_func.compute_points(block)
        npoints = block.npoints()
        lpos = np.array(block.functions_local_to_global())

        # Compute grid_ao on the fly to build grid_lo.
        # The full matrix of grid_ao is [npts, nbasis]. Since the grid is very
        # sparse on atoms, we do not always need the full matrix. `lpos`
        # represents the AOs that have non-zero grid values for the given grid
        # block.
        grid_ao = np.array(points_func.basis_values()["PHI"])[
            :npoints, :lpos.shape[0]]
        grid_lo_blk = grid_lo[npts_count:npts_count+npoints, :]
        grid_lo_blk[:] = grid_ao.dot(C_lo[lpos, :])  # npoints x nlo

        # update block starting position
        npts_count += npoints

    return grid_lo


def form_grid_w(wfn):
    """
    The grid points weights

    Parameters
    ----------
    wfn: psi4.core.HF
        A psi4 HF object that is associated with a DFT calculations.

    Returns
    -------
    grid_w: np.array [npts]
        A vector for the weights of grid points.


    References
    ----------
    psi4numpy/Tutorials/04_Density_Functional_Theory/4b_LDA_kernel.ipynb
    """
    if not isinstance(wfn, psi4.core.HF):
        raise Exception("Unknown type of argument wfn. It has to be the type of psi4.core.HF.")
    # psi4.VBase object to help building grid.
    Vpot = wfn.V_potential()
    # number of grid points
    npts = Vpot.grid().npoints()

    # build grid_w vector
    grid_w = np.zeros((npts,))
    npts_count = 0
    # loop over the blocks to build grid_w
    for b in range(Vpot.nblocks()):
        # Obtain block of weights
        block = Vpot.get_block(b)
        npoints = block.npoints()
        grid_w[npts_count:npts_count+npoints] = np.asarray(block.w())

        # update block starting position
        npts_count += npoints

    return grid_w

def form_occ(wfn, occ={}):
    nbf = wfn.basisset().nbf()
    nelec = [wfn.nalpha(), wfn.nbeta()]
    # Build aufbau occupation.
    rst_occ = [{i: 1 for i in range(n)} for n in nelec]
    for k, v in occ.items():
        k = k.lower()
        spin_chanel = ['alpha', 'beta']
        if k not in spin_chanel:
            raise Exception(f"invalid customized occupation spin chanel: {k}.")
        s = spin_chanel.index(k)
        for orb_i, occ_i in v.items():
            if isinstance(orb_i, str):
                orb_i = orb_i.lower()
                if orb_i not in ['homo', 'lumo']:
                    raise Exception(f"unknown customized occupation index: {orb_i}.")
                if orb_i == 'homo':
                    orb_i = nelec[s] - 1
                else:
                    orb_i = nelec[s]
            if orb_i >= nbf:
                raise Exception(f"customized occupation index is out-of-range: {orb_i} (orbital index) > {nbf} (basis size).")
            if not 0 <= occ_i <= 1:
                raise Exception(f"customized occupation number is invalid: occ={occ_i}.")
            rst_occ[s][orb_i] = occ_i

    occ_idx = []
    occ_val = []
    for d in rst_occ:
        idx_occ = list(d.items())
        idx_occ.sort()
        idx, occ = zip(*idx_occ)
        occ_idx.append(idx)
        occ_val.append(occ)

    nocc = [len(x) for x in occ_idx]

    return nocc, occ_idx, occ_val