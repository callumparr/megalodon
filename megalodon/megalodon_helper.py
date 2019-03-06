import h5py
import numpy as np

ALPHABET = 'ACGT'
BC_NAME = 'basecalls'
BC_OUT_FMTS = ('fasta',)
MAP_NAME = 'mappings'
MAP_OUT_FMTS = ('bam', 'cram', 'sam')
PR_SNP_NAME = 'per_read_snps'
PR_MOD_NAME = 'per_read_mods'
ALIGN_OUTPUTS = set((MAP_NAME, PR_SNP_NAME, PR_MOD_NAME))
OUTPUT_FNS = {
    BC_NAME:'basecalls',
    MAP_NAME:['mappings', 'mappings.summary.txt'],
    PR_SNP_NAME:'per_read_snp_calls.txt',
    PR_MOD_NAME:'per_read_modified_base_calls.txt',
}
COMP_BASES = dict(zip(map(ord, 'ACGT'), map(ord, 'TGCA')))


class MegaError(Exception):
    """ Custom megalodon error for more graceful error handling
    """
    pass

def nstate_to_nbase(nstate):
    return int(np.sqrt(0.25 + (0.5 * nstate)) - 0.5)

def revcomp(seq):
    return seq.translate(COMP_BASES)[::-1]

#############################
##### Signal Extraction #####
#############################

def med_mad(data, factor=None, axis=None, keepdims=False):
    """Compute the Median Absolute Deviation, i.e., the median
    of the absolute deviations from the median, and the median

    :param data: A :class:`ndarray` object
    :param factor: Factor to scale MAD by. Default (None) is to be consistent
    with the standard deviation of a normal distribution
    (i.e. mad( N(0,\sigma^2) ) = \sigma).
    :param axis: For multidimensional arrays, which axis to calculate over
    :param keepdims: If True, axis is kept as dimension of length 1

    :returns: a tuple containing the median and MAD of the data
    """
    if factor is None:
        factor = 1.4826
    dmed = np.median(data, axis=axis, keepdims=True)
    dmad = factor * np.median(abs(data - dmed), axis=axis, keepdims=True)
    if axis is None:
        dmed = dmed.flatten()[0]
        dmad = dmad.flatten()[0]
    elif not keepdims:
        dmed = dmed.squeeze(axis)
        dmad = dmad.squeeze(axis)
    return dmed, dmad

def extract_read_data(fast5_fn, scale=True):
    """Extract raw signal and read id from single fast5 file.
    :returns: tuple containing numpy array with raw signal  and read unique identifier
    """
    # TODO support mutli-fast5
    try:
        fast5_data = h5py.File(fast5_fn, 'r')
    except:
        raise MegaError('Error opening read file')
    try:
        raw_slot = next(iter(fast5_data['/Raw/Reads'].values()))
    except:
        fast5_data.close()
        raise MegaError('Raw signal not found in /Raw/Reads slot')
    try:
        raw_sig = raw_slot['Signal'][:].astype(np.float32)
    except:
        fast5_data.close()
        raise MegaError('Raw signal not found in Signal dataset')
    read_id = None
    try:
        read_id = raw_slot.attrs.get('read_id')
        read_id = read_id.decode()
    except:
        pass
    fast5_data.close()

    if scale:
        med, mad = med_mad(raw_sig)
        raw_sig = (raw_sig - med) / mad

    return raw_sig, read_id


if __name__ == '__main__':
    sys.stderr.write('This is a module. See commands with `megalodon -h`')
    sys.exit(1)