import string
import numpy as np
from collections import defaultdict, namedtuple

from megalodon import megalodon_helper as mh


# model type specific information
TAI_NAME = 'taiyaki'
FLP_NAME = 'flappie'

CAN_ALPHABET = 'ACGT'
MOD_ALPHABET = CAN_ALPHABET + ''.join(
    b for b in string.ascii_uppercase[::-1] if b not in CAN_ALPHABET)


class ModelInfo(object):
    def __init__(
            self, flappie_model_name, taiyaki_model_fn, devices=None,
            num_proc=1, chunk_size=None, chunk_overlap=None,
            max_concur_chunks=None):
        if flappie_model_name is not None:
            self.model_type = FLP_NAME
            self.name = flappie_model_name

            # import module
            import flappy
            self.flappy = flappy

            # compiled flappie models require hardcoding or running fake model
            if flappie_model_name == 'r941_5mC':
                raise NotImplementedError(
                    'Naive modified base flip-flop models are not supported.')
            if flappie_model_name in ('r941_cat_mod', ):
                self.is_cat_mod = True
                can_nmods, output_alphabet = flappy.get_cat_mods()
                self.output_alphabet = output_alphabet
                self.can_nmods = can_nmods
                self.n_mods = self.can_nmods.sum()
                self.output_size = 41 + self.n_mods
                self.can_indices = np.cumsum(np.concatenate(
                    [[0], self.can_nmods[:-1] + 1]))
                can_bases = ''.join(
                    output_alphabet[b_i] for b_i in self.can_indices)
                mod_bases = ''.join(
                    output_alphabet[b_i + 1:b_i + 1 + b_nmods]
                    for b_i, b_nmods in zip(self.can_indices, self.can_nmods))
                self.can_alphabet = can_bases
                self.mod_long_names = [(mod_b, mod_b) for mod_b in mod_bases]
                self.can_base_mod = defaultdict(list)
                for base in self.output_alphabet:
                    if base in can_bases:
                        curr_can_base = base
                    else:
                        self.can_base_mod[curr_can_base].append(base)
                self.can_base_mods = dict(self.can_base_mods)
            else:
                self.is_cat_mod = False
                self.can_alphabet = mh.ALPHABET
                self.mod_long_names = []
                self.output_size = 40
                self.n_mods = 0
            # flappie is CPU only
            self.process_devices = [None] * num_proc
        elif taiyaki_model_fn is not None:
            if any(arg is None for arg in (
                    chunk_size, chunk_overlap, max_concur_chunks)):
                raise NotImplementedError(
                    'Must provide chunk_size, chunk_overlap, ' +
                    'max_concur_chunks in order to run the taiyaki ' +
                    'base calling backend.')
            self.model_type = TAI_NAME
            self.fn = taiyaki_model_fn
            self.chunk_size = chunk_size
            self.chunk_overlap = chunk_overlap
            self.max_concur_chunks = max_concur_chunks

            self.devices = devices
            base_proc_per_device = np.ceil(num_proc / len(devices)).astype(int)
            procs_per_device = np.repeat(base_proc_per_device, len(devices))
            if base_proc_per_device * len(devices) > num_proc:
                procs_per_device[
                    -(base_proc_per_device * len(devices) - num_proc):] -= 1
            assert sum(procs_per_device) == num_proc
            self.process_devices = [
                int(dv) for dv in np.repeat(devices, procs_per_device)]

            # import modules
            from taiyaki.helpers import load_model as load_taiyaki_model
            from taiyaki.basecall_helpers import run_model as tai_run_model
            try:
                from taiyaki.layers import GlobalNormFlipFlopCatMod
            except ImportError:
                GlobalNormFlipFlopCatMod = None
            import torch

            # store modules in object
            self.load_taiyaki_model = load_taiyaki_model
            self.tai_run_model = tai_run_model
            self.torch = torch

            tmp_model = self.load_taiyaki_model(taiyaki_model_fn)
            ff_layer = tmp_model.sublayers[-1]
            self.is_cat_mod = (
                GlobalNormFlipFlopCatMod is not None and isinstance(
                    ff_layer, GlobalNormFlipFlopCatMod))
            self.output_size = ff_layer.size
            if self.is_cat_mod:
                # TODO everything here can be derived from the json attributes
                # can_nmods, output_alphabet and modified_base_long_names
                # should be converted to use only these attributes to allow
                # a bit more flexability for the taiyaki layer attributes
                self.output_alphabet = ff_layer.output_alphabet
                self.can_indices = np.cumsum(np.concatenate(
                    [[0], ff_layer.can_nmods[:-1] + 1]))
                self.can_alphabet = ''.join(self.output_alphabet[b_i]
                                            for b_i in self.can_indices)
                self.mod_long_names = list(ff_layer.mod_long_names_conv.items())
                self.str_to_int_mod_labels = {}
                self.can_base_mods = defaultdict(list)
                for base_i, base in enumerate(self.output_alphabet):
                    if base_i in self.can_indices:
                        curr_can_base = base
                        curr_mod_i = 0
                    else:
                        self.str_to_int_mod_labels[base] = curr_mod_i
                        self.can_base_mods[curr_can_base].append(base)
                        curr_mod_i += 1
                self.can_base_mods = dict(self.can_base_mods)
            else:
                if mh.nstate_to_nbase(ff_layer.size) != 4:
                    raise NotImplementedError(
                        'Naive modified base flip-flop models are not ' +
                        'supported.')
                self.output_alphabet = mh.ALPHABET
                self.can_alphabet = mh.ALPHABET
                self.mod_long_names = []
                self.str_to_int_mod_labels = {}
            self.n_mods = len(self.mod_long_names)
        else:
            raise mh.MegaError('Invalid model specification.')

        return

    def prep_model_worker(self, device):
        if self.model_type == TAI_NAME:
            # setup for taiyaki model
            self.model = self.load_taiyaki_model(self.fn)
            if device is not None:
                self.device = self.torch.device(device)
                self.torch.cuda.set_device(self.device)
                self.model = self.model.cuda()
            else:
                self.device = self.torch.device('cpu')
            self.model = self.model.eval()

        return

    def run_model(self, raw_sig, n_can_state=None):
        if self.model_type == FLP_NAME:
            rt = self.flappy.RawTable(raw_sig)
            # flappy will return split bc and mods based on model
            trans_weights = self.flappy.run_network(rt, self.name)
        elif self.model_type == TAI_NAME:
            try:
                trans_weights = self.tai_run_model(
                    raw_sig, self.model, self.chunk_size, self.chunk_overlap,
                    self.max_concur_chunks)
            except AttributeError:
                raise mh.MegaError('Out of date or incompatible model')
            except RuntimeError:
                raise mh.MegaError('Likely out of memory error.')
            if self.device != self.torch.device('cpu'):
                self.torch.cuda.empty_cache()
            if n_can_state is not None:
                trans_weights = (
                    np.ascontiguousarray(trans_weights[:,:n_can_state]),
                    np.ascontiguousarray(trans_weights[:,n_can_state:]))
        else:
            raise mh.MegaError('Invalid model type.')

        return trans_weights


if __name__ == '__main__':
    sys.stderr.write('This is a module. See commands with `megalodon -h`')
    sys.exit(1)
