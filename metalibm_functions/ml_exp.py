# -*- coding: utf-8 -*-

import sys

from pythonsollya import *

from metalibm_core.core.attributes import ML_Debug
from metalibm_core.core.ml_operations import *
from metalibm_core.core.ml_formats import *
from metalibm_core.targets.generic_processor import GenericProcessor
from metalibm_core.targets.vector_backend import VectorBackend
from metalibm_core.core.polynomials import *
from metalibm_core.core.ml_table import ML_Table
from metalibm_core.core.ml_function import ML_Function, ML_FunctionBasis
from metalibm_core.code_generation.generator_utility import FunctionOperator, FO_Result, FO_Arg
from metalibm_core.core.ml_complex_formats import ML_Mpfr_t


from metalibm_core.utility.ml_template import ML_ArgTemplate
from metalibm_core.utility.log_report  import Log
from metalibm_core.utility.debug_utils import *
from metalibm_core.utility.num_utils   import ulp
from metalibm_core.utility.gappa_utils import is_gappa_installed



class ML_Exponential(ML_Function("ml_exp")):
    def __init__(self, 
                 precision = ML_Binary32, 
                 accuracy  = ML_Faithful,
                 libm_compliant = True, 
                 debug_flag = False, 
                 fuse_fma = True, 
                 fast_path_extract = True,
                 target = GenericProcessor(), 
                 output_file = "expf.c", 
                 function_name = "expf",
                 language = C_Code,
                 vector_size = 1):
        # initializing I/O precision
        io_precisions = [precision] * 2

        # initializing base class
        ML_FunctionBasis.__init__(self, 
          base_name = "exp",
          function_name = function_name,
          output_file = output_file,

          io_precisions = io_precisions,
          abs_accuracy = None,
          libm_compliant = libm_compliant,

          processor = target,
          fuse_fma = fuse_fma,
          fast_path_extract = fast_path_extract,

          debug_flag = debug_flag,
          language = language,
          vector_size = vector_size
        )

        self.accuracy  = accuracy
        self.precision = precision

    def generate_scheme(self):
        # declaring target and instantiating optimization engine

        vx = self.implementation.add_input_variable("x", self.precision) 

        Log.set_dump_stdout(True)

        Log.report(Log.Info, "\033[33;1m generating implementation scheme \033[0m")
        if self.debug_flag: 
            Log.report(Log.Info, "\033[31;1m debug has been enabled \033[0;m")

        # local overloading of RaiseReturn operation
        def ExpRaiseReturn(*args, **kwords):
            kwords["arg_value"] = vx
            kwords["function_name"] = self.function_name
            return RaiseReturn(*args, **kwords)


        test_nan_or_inf = Test(vx, specifier = Test.IsInfOrNaN, likely = False, debug = debug_multi, tag = "nan_or_inf")
        test_nan = Test(vx, specifier = Test.IsNaN, debug = debug_multi, tag = "is_nan_test")
        test_positive = Comparison(vx, 0, specifier = Comparison.GreaterOrEqual, debug = debug_multi, tag = "inf_sign")

        test_signaling_nan = Test(vx, specifier = Test.IsSignalingNaN, debug = debug_multi, tag = "is_signaling_nan")
        return_snan = Statement(ExpRaiseReturn(ML_FPE_Invalid, return_value = FP_QNaN(self.precision)))

        # return in case of infinity input
        infty_return = Statement(ConditionBlock(test_positive, Return(FP_PlusInfty(self.precision)), Return(FP_PlusZero(self.precision))))
        # return in case of specific value input (NaN or inf)
        specific_return = ConditionBlock(test_nan, ConditionBlock(test_signaling_nan, return_snan, Return(FP_QNaN(self.precision))), infty_return)
        # return in case of standard (non-special) input

        # exclusion of early overflow and underflow cases
        precision_emax      = self.precision.get_emax()
        precision_max_value = S2 * S2**precision_emax 
        exp_overflow_bound  = ceil(log(precision_max_value))
        early_overflow_test = Comparison(vx, exp_overflow_bound, likely = False, specifier = Comparison.Greater)
        early_overflow_return = Statement(ClearException(), ExpRaiseReturn(ML_FPE_Inexact, ML_FPE_Overflow, return_value = FP_PlusInfty(self.precision)))

        precision_emin = self.precision.get_emin_subnormal()
        precision_min_value = S2 ** precision_emin
        exp_underflow_bound = floor(log(precision_min_value))


        early_underflow_test = Comparison(vx, exp_underflow_bound, likely = False, specifier = Comparison.Less)
        early_underflow_return = Statement(ClearException(), ExpRaiseReturn(ML_FPE_Inexact, ML_FPE_Underflow, return_value = FP_PlusZero(self.precision)))


        sollya_prec_map = {ML_Binary32: binary32, ML_Binary64: binary64}


        # constant computation
        invlog2 = round(1/log(2), sollya_prec_map[self.precision], RN)

        interval_vx = Interval(exp_underflow_bound, exp_overflow_bound)
        interval_fk = interval_vx * invlog2
        interval_k = Interval(floor(inf(interval_fk)), ceil(sup(interval_fk)))


        log2_hi_precision = self.precision.get_field_size() - (ceil(log2(sup(abs(interval_k)))) + 2)
        Log.report(Log.Info, "log2_hi_precision: %d" % log2_hi_precision)
        invlog2_cst = Constant(invlog2, precision = self.precision)
        log2_hi = round(log(2), log2_hi_precision, RN) 
        log2_lo = round(log(2) - log2_hi, sollya_prec_map[self.precision], RN)

        # argument reduction
        unround_k = vx * invlog2
        unround_k.set_attributes(tag = "unround_k", debug = debug_multi)
        k = NearestInteger(unround_k, precision = self.precision, debug = debug_multi)
        ik = NearestInteger(unround_k, precision = ML_Int32, debug = debug_multi, tag = "ik")
        ik.set_tag("ik")
        k.set_tag("k")
        exact_pre_mul = (k * log2_hi)
        exact_pre_mul.set_attributes(exact= True)
        exact_hi_part = vx - exact_pre_mul
        exact_hi_part.set_attributes(exact = True, tag = "exact_hi", debug = debug_multi, prevent_optimization = True)
        exact_lo_part = - k * log2_lo
        exact_lo_part.set_attributes(tag = "exact_lo", debug = debug_multi, prevent_optimization = True)
        r =  exact_hi_part + exact_lo_part 
        r.set_tag("r")
        r.set_attributes(debug = debug_multi)

        approx_interval = Interval(-log(2)/2, log(2)/2)

        approx_interval_half = approx_interval / 2
        approx_interval_split = [Interval(-log(2)/2, inf(approx_interval_half)), approx_interval_half, Interval(sup(approx_interval_half), log(2)/2)]

        # TODO: should be computed automatically
        exact_hi_interval = approx_interval
        exact_lo_interval = - interval_k * log2_lo


        # opt_r = self.opt_engine.optimization_process(r, self.precision, copy = True, fuse_fma = fuse_fma)
        opt_r = self.optimise_scheme(r, copy = {})

        tag_map = {}
        self.opt_engine.register_nodes_by_tag(opt_r, tag_map)

        cg_eval_error_copy_map = {
            vx: Variable("x", precision = self.precision, interval = interval_vx),
            tag_map["k"]: Variable("k", interval = interval_k, precision = self.precision)
        }

        #try:
        if is_gappa_installed():
            #eval_error = gappacg.get_eval_error(opt_r, cg_eval_error_copy_map, gappa_filename = "red_arg.g")
            eval_error = self.gappa_engine.get_eval_error_v2(self.opt_engine, opt_r, cg_eval_error_copy_map, gappa_filename = "red_arg.g")
        else:
            eval_error = 0.0
            Log.report(Log.Warning, "gappa is not installed in this environnement")
        Log.report(Log.Info, "eval error: %s" % eval_error)
        #except:
        #    Log.report(Log.Info, "gappa error evaluation failed")


        local_ulp = sup(ulp(exp(approx_interval), self.precision))
        print "ulp: ", local_ulp 
        Log.report(Log.Info, "accuracy: %s" % self.accuracy)
        if self.accuracy is ML_Faithful:
            error_goal = local_ulp
        elif self.accuracy is ML_CorrectlyRounded:
            error_goal = S2**-1 * local_ulp
        elif isinstance(self.accuracy, ML_DegradedAccuracyAbsolute):
            error_goal = self.accuracy.goal
        elif isinstance(self.accuracy, ML_DegradedAccuracyRelative):
            error_goal = self.accuracy.goal
        else:
            Log.report(Log.Error, "unknown accuracy: %s" % self.accuracy)

            

        # error_goal = local_ulp #S2**-(self.precision.get_field_size()+1)
        error_goal_approx = S2**-1 * error_goal

        Log.report(Log.Info, "\033[33;1m building mathematical polynomial \033[0m\n")
        poly_degree = max(sup(guessdegree(expm1(x)/x, approx_interval, error_goal_approx)) - 1, 2)
        init_poly_degree = poly_degree


        error_function = lambda p, f, ai, mod, t: dirtyinfnorm(f - p, ai)

        polynomial_scheme_builder = PolynomialSchemeEvaluator.generate_estrin_scheme
        #polynomial_scheme_builder = PolynomialSchemeEvaluator.generate_horner_scheme

        while 1:
            Log.report(Log.Info, "attempting poly degree: %d" % poly_degree)
            precision_list = [1] + [self.precision] * (poly_degree)
            poly_object, poly_approx_error = Polynomial.build_from_approximation_with_error(expm1(x), poly_degree, precision_list, approx_interval, absolute, error_function = error_function)
            Log.report(Log.Info, "polynomial: %s " % poly_object)
            sub_poly = poly_object.sub_poly(start_index = 2)
            Log.report(Log.Info, "polynomial: %s " % sub_poly)

            Log.report(Log.Info, "poly approx error: %s" % poly_approx_error)

            Log.report(Log.Info, "\033[33;1m generating polynomial evaluation scheme \033[0m")
            pre_poly = polynomial_scheme_builder(poly_object, r, unified_precision = self.precision)
            pre_poly.set_attributes(tag = "pre_poly", debug = debug_multi)

            pre_sub_poly = polynomial_scheme_builder(sub_poly, r, unified_precision = self.precision)
            pre_sub_poly.set_attributes(tag = "pre_sub_poly", debug = debug_multi)

            poly = 1 + (exact_hi_part + (exact_lo_part + pre_sub_poly))
            poly.set_tag("poly")

            # optimizing poly before evaluation error computation
            #opt_poly = self.opt_engine.optimization_process(poly, self.precision, fuse_fma = fuse_fma)
            #opt_sub_poly = self.opt_engine.optimization_process(pre_sub_poly, self.precision, fuse_fma = fuse_fma)
            opt_poly = self.optimise_scheme(poly)
            opt_sub_poly = self.optimise_scheme(pre_sub_poly)

            # evaluating error of the polynomial approximation
            r_gappa_var        = Variable("r", precision = self.precision, interval = approx_interval)
            exact_hi_gappa_var = Variable("exact_hi", precision = self.precision, interval = exact_hi_interval)
            exact_lo_gappa_var = Variable("exact_lo", precision = self.precision, interval = exact_lo_interval)
            vx_gappa_var       = Variable("x", precision = self.precision, interval = interval_vx)
            k_gappa_var        = Variable("k", interval = interval_k, precision = self.precision)


            #print "exact_hi interval: ", exact_hi_interval

            sub_poly_error_copy_map = {
                #r.get_handle().get_node(): r_gappa_var,
                #vx.get_handle().get_node():  vx_gappa_var,
                exact_hi_part.get_handle().get_node(): exact_hi_gappa_var,
                exact_lo_part.get_handle().get_node(): exact_lo_gappa_var,
                #k.get_handle().get_node(): k_gappa_var,
            }

            poly_error_copy_map = {
                exact_hi_part.get_handle().get_node(): exact_hi_gappa_var,
                exact_lo_part.get_handle().get_node(): exact_lo_gappa_var,
            }


            if is_gappa_installed():
                sub_poly_eval_error = -1.0
                #print "gappacg :", gappacg.memoization_map, gappacg.exact_hint_map 
                #print exact_hi_part.get_handle().get_node().get_str(depth = 0, memoization_map = {}, display_id = True)
                #print exact_lo_part.get_handle().get_node().get_str(depth = 0, memoization_map = {}, display_id = True)
                #print opt_sub_poly.get_str(depth = None, memoization_map = {}, display_id = True)
                sub_poly_eval_error = self.gappa_engine.get_eval_error_v2(self.opt_engine, opt_sub_poly, sub_poly_error_copy_map, gappa_filename = "%s_gappa_sub_poly.g" % self.function_name)
                #poly_eval_error     = gappacg.get_eval_error_v2(opt_eng, opt_poly, poly_error_copy_map, gappa_filename = "gappa_poly.g")

                dichotomy_map = [
                    {
                        exact_hi_part.get_handle().get_node(): approx_interval_split[0],
                    },
                    {
                        exact_hi_part.get_handle().get_node(): approx_interval_split[1],
                    },
                    {
                        exact_hi_part.get_handle().get_node(): approx_interval_split[2],
                    },
                ]
                poly_eval_error_dico = self.gappa_engine.get_eval_error_v3(self.opt_engine, opt_poly, poly_error_copy_map, gappa_filename = "gappa_poly.g", dichotomy = dichotomy_map)
                print "poly_eval_error_dico: ", poly_eval_error_dico
                #sys.exit(1)

                poly_eval_error = max([sup(abs(err)) for err in poly_eval_error_dico])
            else:
                poly_eval_error = 0.0
                Log.report(Log.Warning, "gappa is not installed in this environnement")
            Log.report(Log.Info, "poly evaluation error: %s" % poly_eval_error)
            Log.report(Log.Info, "sub poly evaluation error: %s" % sub_poly_eval_error)

            global_poly_error     = None
            global_rel_poly_error = None

            for case_index in xrange(3):
                poly_error = poly_approx_error + poly_eval_error_dico[case_index]
                rel_poly_error = sup(abs(poly_error / exp(approx_interval_split[case_index])))
                if global_rel_poly_error == None or rel_poly_error > global_rel_poly_error:
                    global_rel_poly_error = rel_poly_error
                    global_poly_error = poly_error
            print "global_rel_poly_error: ", global_rel_poly_error, global_rel_poly_error.__class__
            flag = error_goal > global_rel_poly_error


            if flag:
                break
            else:
                poly_degree += 1




        late_overflow_test = Comparison(ik, self.precision.get_emax(), specifier = Comparison.Greater, likely = False, debug = debug_multi, tag = "late_overflow_test")
        overflow_exp_offset = (self.precision.get_emax() - self.precision.get_field_size() / 2)
        diff_k = ik - overflow_exp_offset 
        diff_k.set_attributes(debug = debug_multi, tag = "diff_k")
        late_overflow_result = (ExponentInsertion(diff_k, precision = self.precision) * poly) * ExponentInsertion(overflow_exp_offset, precision = self.precision)
        late_overflow_result.set_attributes(silent = False, tag = "late_overflow_result", debug = debug_multi, precision = self.precision)
        late_overflow_return = ConditionBlock(Test(late_overflow_result, specifier = Test.IsInfty, likely = False), ExpRaiseReturn(ML_FPE_Overflow, return_value = FP_PlusInfty(self.precision)), Return(late_overflow_result))

        late_underflow_test = Comparison(k, self.precision.get_emin_normal(), specifier = Comparison.LessOrEqual, likely = False)
        underflow_exp_offset = 2 * self.precision.get_field_size()
        late_underflow_result = (ExponentInsertion(ik + underflow_exp_offset, precision = self.precision) * poly) * ExponentInsertion(-underflow_exp_offset, precision = self.precision)
        late_underflow_result.set_attributes(debug = debug_multi, tag = "late_underflow_result", silent = False)
        test_subnormal = Test(late_underflow_result, specifier = Test.IsSubnormal)
        late_underflow_return = Statement(ConditionBlock(test_subnormal, ExpRaiseReturn(ML_FPE_Underflow, return_value = late_underflow_result)), Return(late_underflow_result))

        twok = ExponentInsertion(ik, tag = "exp_ik", debug = debug_multi, precision = self.precision)
        #std_result = twok * ((1 + exact_hi_part * pre_poly) + exact_lo_part * pre_poly) 
        std_result = twok * poly
        std_result.set_attributes(tag = "std_result", debug = debug_multi)
        result_scheme = ConditionBlock(late_overflow_test, late_overflow_return, ConditionBlock(late_underflow_test, late_underflow_return, Return(std_result)))
        std_return = ConditionBlock(early_overflow_test, early_overflow_return, ConditionBlock(early_underflow_test, early_underflow_return, result_scheme))

        # main scheme
        Log.report(Log.Info, "\033[33;1m MDL scheme \033[0m")
        scheme = ConditionBlock(test_nan_or_inf, Statement(ClearException(), specific_return), std_return)

        return scheme

    def generate_emulate(self, result_ternary, result, mpfr_x, mpfr_rnd):
        """ generate the emulation code for ML_Log2 functions
            mpfr_x is a mpfr_t variable which should have the right precision
            mpfr_rnd is the rounding mode
        """
        emulate_func_name = "mpfr_exp"
        emulate_func_op = FunctionOperator(emulate_func_name, arg_map = {0: FO_Arg(0), 1: FO_Arg(1), 2: FO_Arg(2)}, require_header = ["mpfr.h"]) 
        emulate_func   = FunctionObject(emulate_func_name, [ML_Mpfr_t, ML_Mpfr_t, ML_Int32], ML_Int32, emulate_func_op)
        mpfr_call = Statement(ReferenceAssign(result_ternary, emulate_func(result, mpfr_x, mpfr_rnd)))

        return mpfr_call


if __name__ == "__main__":
    # auto-test
    arg_template = ML_ArgTemplate(default_function_name = "new_exp", default_output_file = "new_exp.c" )
    # argument extraction 
    parse_arg_index_list = arg_template.sys_arg_extraction()
    arg_template.check_args(parse_arg_index_list)


    ml_exp          = ML_Exponential(arg_template.precision, 
                                  libm_compliant            = arg_template.libm_compliant, 
                                  debug_flag                = arg_template.debug_flag, 
                                  target                    = arg_template.target, 
                                  fuse_fma                  = arg_template.fuse_fma, 
                                  fast_path_extract         = arg_template.fast_path,
                                  function_name             = arg_template.function_name,
                                  accuracy                  = arg_template.accuracy,
                                  output_file               = arg_template.output_file, 
                                  language                  = arg_template.language,
                                  vector_size               = arg_template.vector_size)

    ml_exp.gen_implementation()
