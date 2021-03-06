# -*- coding: utf-8 -*-

import sys

from sollya import S2, Interval

from metalibm_core.core.ml_function import ML_Function, ML_FunctionBasis

from metalibm_core.core.attributes import ML_Debug
from metalibm_core.core.ml_operations import *

from metalibm_core.core.ml_formats import *
from metalibm_core.core.ml_complex_formats import * 

from metalibm_core.code_generation.c_code_generator import CCodeGenerator
from metalibm_core.code_generation.generic_processor import GenericProcessor
from metalibm_core.code_generation.mpfr_backend import MPFRProcessor
from metalibm_core.targets.common.fixed_point_backend import FixedPointBackend
from metalibm_core.targets.common.vector_backend import VectorBackend
from metalibm_core.code_generation.code_object import CodeObject
from metalibm_core.code_generation.code_function import CodeFunction
from metalibm_core.code_generation.code_constant import C_Code 
from metalibm_core.core.ml_optimization_engine import OptimizationEngine
from metalibm_core.core.polynomials import *
from metalibm_core.core.ml_table import ML_Table

from metalibm_core.utility.ml_template import *

from metalibm_core.utility.arg_utils import test_flag_option, extract_option_value  

from metalibm_core.utility.debug_utils import * 




class ML_UT_VectorCode(ML_Function("ml_ut_vector_code")):
  def __init__(self, 
                 arg_template,
                 precision = ML_Binary32, 
                 abs_accuracy = S2**-24, 
                 libm_compliant = True, 
                 debug_flag = False, 
                 fuse_fma = True, 
                 fast_path_extract = True,
                 target = FixedPointBackend(), 
                 output_file = "ut_vector_code.c", 
                 function_name = "ut_vector_code"):
    # precision argument extraction
    precision = ArgDefault.select_value([arg_template.precision, precision])
    io_precisions = [precision] * 2

    # initializing base class
    ML_FunctionBasis.__init__(self, 
      base_name = "ut_vector_code",
      function_name = function_name,
      output_file = output_file,

      io_precisions = io_precisions,
      abs_accuracy = None,
      libm_compliant = libm_compliant,

      processor = target,
      fuse_fma = fuse_fma,
      fast_path_extract = fast_path_extract,

      debug_flag = debug_flag,
      arg_template = arg_template
    )

    self.precision = precision


  def generate_function_list(self):
    # declaring function input variable
    vx = self.implementation.add_input_variable("x", self.precision)
    vy = self.implementation.add_input_variable("y", self.precision)
    # declaring specific interval for input variable <x>
    vx.set_interval(Interval(-1, 1))


    vec = Variable("vec", precision = ML_Float2, var_type = Variable.Local)

    vec2 = Multiplication(vec, vec, precision = ML_Float2)
    vec3 = Addition(vec, vec2, precision = ML_Float2)

    result = Addition(vec3[0], vec3[1], precision = ML_Binary32)

    scheme = Statement(
      ReferenceAssign(vec[0], vx),
      ReferenceAssign(vec[1], vy),
      Return(result)
    )

    # dummy scheme to make functionnal code generation
    self.implementation.set_scheme(scheme)

    return [self.implementation]

if __name__ == "__main__":
  # auto-test
  arg_template = ML_NewArgTemplate("new_ut_vector_code", default_output_file = "new_ut_vector_code.c" )
  args = arg_template.arg_extraction()

  ml_ut_vector_code = ML_UT_VectorCode(args)

  display_after_gen = ArgDefault.select_value([args.display_after_gen])
  display_after_opt = ArgDefault.select_value([args.display_after_opt])

  ml_ut_vector_code.gen_implementation(display_after_gen = display_after_gen, display_after_opt = display_after_opt)


