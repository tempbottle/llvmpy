#
# Copyright (c) 2008-10, Mahadevan R All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
#  * Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
#  * Neither the name of this software, nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

"Execution Engine and related classes."

from io import BytesIO
import contextlib

import llvm
from llvm import core
from llvm.passes import TargetData, TargetTransformInfo
from llvmpy import api, extra
#===----------------------------------------------------------------------===
# Enumerations
#===----------------------------------------------------------------------===

BO_BIG_ENDIAN       = 0
BO_LITTLE_ENDIAN    = 1

# CodeModel
CM_DEFAULT      = api.llvm.CodeModel.Model.Default
CM_JITDEFAULT   = api.llvm.CodeModel.Model.JITDefault
CM_SMALL        = api.llvm.CodeModel.Model.Small
CM_KERNEL       = api.llvm.CodeModel.Model.Kernel
CM_MEDIUM       = api.llvm.CodeModel.Model.Medium
CM_LARGE        = api.llvm.CodeModel.Model.Large

# Reloc
RELOC_DEFAULT        = api.llvm.Reloc.Model.Default
RELOC_STATIC         = api.llvm.Reloc.Model.Static
RELOC_PIC            = api.llvm.Reloc.Model.PIC_
RELOC_DYNAMIC_NO_PIC = api.llvm.Reloc.Model.DynamicNoPIC

#===----------------------------------------------------------------------===
# Generic value
#===----------------------------------------------------------------------===

class GenericValue(llvm.Wrapper):

    @staticmethod
    def int(ty, intval):
        ptr = api.llvm.GenericValue.CreateInt(ty._ptr, int(intval), False)
        return GenericValue(ptr)

    @staticmethod
    def int_signed(ty, intval):
        ptr = api.llvm.GenericValue.CreateInt(ty._ptr, int(intval), True)
        return GenericValue(ptr)

    @staticmethod
    def real(ty, floatval):
        if str(ty) == 'float':
            ptr = api.llvm.GenericValue.CreateFloat(float(floatval))
        elif str(ty) == 'double':
            ptr = api.llvm.GenericValue.CreateDouble(float(floatval))
        else:
            raise Exception('Unreachable')
        return GenericValue(ptr)

    @staticmethod
    def pointer(addr):
        '''
        One argument version takes (addr).
        Two argument version takes (ty, addr). [Deprecated]

        `ty` is unused.
        `addr` is an integer representing an address.

        '''
        ptr = api.llvm.GenericValue.CreatePointer(int(addr))
        return GenericValue(ptr)

    def as_int(self):
        return self._ptr.toUnsignedInt()

    def as_int_signed(self):
        return self._ptr.toSignedInt()

    def as_real(self, ty):
        return self._ptr.toFloat(ty._ptr)

    def as_pointer(self):
        return self._ptr.toPointer()

#===----------------------------------------------------------------------===
# Engine builder
#===----------------------------------------------------------------------===

class EngineBuilder(llvm.Wrapper):
    @staticmethod
    def new(module):
        ptr = api.llvm.EngineBuilder.new(module._ptr)
        return EngineBuilder(ptr)

    def force_jit(self):
        self._ptr.setEngineKind(api.llvm.EngineKind.Kind.JIT)
        return self

    def force_interpreter(self):
        self._ptr.setEngineKind(api.llvm.EngineKind.Kind.Interpreter)
        return self

    def opt(self, level):
        '''
        level valid [0, 1, 2, 3] -- [None, Less, Default, Aggressive]
        '''
        assert 0 <= level <= 3
        self._ptr.setOptLevel(level)
        return self

    def mattrs(self, string):
        '''set machine attributes as a comma/space separated string

        e.g: +sse,-3dnow
        '''
        self._ptr.setMAttrs(string.split(','))
        return self

    def create(self, tm=None):
        '''
        tm --- Optional. Provide a TargetMachine.  Ownership is transfered
        to the returned execution engine.
        '''
        if tm is not None:
            engine = self._ptr.create(tm._ptr)
        else:
            engine = self._ptr.create()
        return ExecutionEngine(engine)

    def select_target(self, *args):
        '''get the corresponding target machine

        Accept no arguments or (triple, march, mcpu, mattrs)
        '''
        if args:
            triple, march, mcpu, mattrs = args
            ptr = self._ptr.selectTarget(triple, march, mcpu,
                                          mattrs.split(','))
        else:
            ptr = self._ptr.selectTarget()
        return TargetMachine(ptr)


#===----------------------------------------------------------------------===
# Execution engine
#===----------------------------------------------------------------------===

class ExecutionEngine(llvm.Wrapper):

    @staticmethod
    def new(module, force_interpreter=False):
        eb = EngineBuilder.new(module)
        if force_interpreter:
            eb.force_interpreter()
        return eb.create()

    def disable_lazy_compilation(self, disabled=True):
        self._ptr.DisableLazyCompilation(disabled)

    def run_function(self, fn, args):
        ptr = self._ptr.runFunction(fn._ptr, list(map(lambda x: x._ptr, args)))
        return GenericValue(ptr)

    def get_pointer_to_function(self, fn):
        return self._ptr.getPointerToFunction(fn._ptr)

    def get_pointer_to_global(self, val):
        return self._ptr.getPointerToGlobal(val._ptr)

    def add_global_mapping(self, gvar, addr):
        assert addr >= 0, "Address cannot not be negative"
        self._ptr.addGlobalMapping(gvar._ptr, addr)

    def run_static_ctors(self):
        self._ptr.runStaticConstructorsDestructors(False)

    def run_static_dtors(self):
        self._ptr.runStaticConstructorsDestructors(True)

    def free_machine_code_for(self, fn):
        self._ptr.freeMachineCodeForFunction(fn._ptr)

    def add_module(self, module):
        self._ptr.addModule(module._ptr)

    def remove_module(self, module):
        return self._ptr.removeModule(module._ptr)

    @property
    def target_data(self):
        ptr = self._ptr.getDataLayout()
        return TargetData(ptr)

#===----------------------------------------------------------------------===
# Target machine
#===----------------------------------------------------------------------===

def initialize_target(target, noraise=False):
    """Initialize target by name.
    It is safe to initialize the same target multiple times.
    """
    prefix = 'LLVMInitialize'
    postfixes = ['Target', 'TargetInfo', 'TargetMC', 'AsmPrinter']
    try:
        for postfix in postfixes:
            getattr(api, '%s%s%s' % (prefix, target, postfix))()
    except AttributeError:
        if noraise:
            return False
        else:
            raise
    else:
        return True


def print_registered_targets():
    '''
    Note: print directly to stdout
    '''
    api.llvm.TargetRegistry.printRegisteredTargetsForVersion()

def get_host_cpu_name():
    '''return the string name of the host CPU
    '''
    return api.llvm.sys.getHostCPUName()

def get_default_triple():
    '''return the target triple of the host in str-rep
    '''
    return api.llvm.sys.getDefaultTargetTriple()


class TargetMachine(llvm.Wrapper):

    @staticmethod
    def new(triple='', cpu='', features='', opt=2, cm=CM_DEFAULT,
            reloc=RELOC_DEFAULT):
        if not triple:
            triple = get_default_triple()
        if not cpu:
            cpu = get_host_cpu_name()
        with contextlib.closing(BytesIO()) as error:
            target = api.llvm.TargetRegistry.lookupTarget(triple, error)
            if not target:
                raise llvm.LLVMException(error)
            if not target.hasTargetMachine():
                raise llvm.LLVMException(target, "No target machine.")
            target_options = api.llvm.TargetOptions.new()
            tm = target.createTargetMachine(triple, cpu, features,
                                            target_options,
                                            reloc, cm, opt)
            if not tm:
                raise llvm.LLVMException("Cannot create target machine")
            return TargetMachine(tm)

    @staticmethod
    def lookup(arch, cpu='', features='', opt=2, cm=CM_DEFAULT,
               reloc=RELOC_DEFAULT):
        '''create a targetmachine given an architecture name

            For a list of architectures,
            use: `llc -help`

            For a list of available CPUs,
            use: `llvm-as < /dev/null | llc -march=xyz -mcpu=help`

            For a list of available attributes (features),
            use: `llvm-as < /dev/null | llc -march=xyz -mattr=help`
            '''
        triple = api.llvm.Triple.new()
        with contextlib.closing(BytesIO()) as error:
            target = api.llvm.TargetRegistry.lookupTarget(arch, triple, error)
            if not target:
                raise llvm.LLVMException(error.getvalue())
            if not target.hasTargetMachine():
                raise llvm.LLVMException(target, "No target machine.")
            target_options = api.llvm.TargetOptions.new()
            tm = target.createTargetMachine(str(triple), cpu, features,
                                            target_options,
                                            reloc, cm, opt)
            if not tm:
                raise llvm.LLVMException("Cannot create target machine")
            return TargetMachine(tm)

    def _emit_file(self, module, cgft):
        pm = api.llvm.PassManager.new()
        os = extra.make_raw_ostream_for_printing()
        pm.add(api.llvm.DataLayout.new(str(self.target_data)))
        failed = self._ptr.addPassesToEmitFile(pm, os, cgft)
        pm.run(module)


        CGFT = api.llvm.TargetMachine.CodeGenFileType
        if cgft == CGFT.CGFT_ObjectFile:
            return os.bytes()
        else:
            return os.str()

    def emit_assembly(self, module):
        '''returns byte string of the module as assembly code of the target machine
        '''
        CGFT = api.llvm.TargetMachine.CodeGenFileType
        return self._emit_file(module._ptr, CGFT.CGFT_AssemblyFile)

    def emit_object(self, module):
        '''returns byte string of the module as native code of the target machine
        '''
        CGFT = api.llvm.TargetMachine.CodeGenFileType
        return self._emit_file(module._ptr, CGFT.CGFT_ObjectFile)

    @property
    def target_data(self):
        '''get target data of this machine
        '''
        return TargetData(self._ptr.getDataLayout())

    @property
    def target_name(self):
        return self._ptr.getTarget().getName()

    @property
    def target_short_description(self):
        return self._ptr.getTarget().getShortDescription()

    @property
    def triple(self):
        return self._ptr.getTargetTriple()

    @property
    def cpu(self):
        return self._ptr.getTargetCPU()

    @property
    def feature_string(self):
        return self._ptr.getTargetFeatureString()

