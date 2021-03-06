# -*- coding: utf-8 -*-

###############################################################################
# This file is part of Kalray's Metalibm tool
# Copyright (2014)
# All rights reserved
# created:          Apr 23th,  2014
# last-modified:    Mar 16th, 2016
#
# author(s): Nicolas Brunie (nicolas.brunie@kalray.eu)
###############################################################################

import sys
import argparse

from sollya import Interval

from .arg_utils import extract_option_value, test_flag_option
from .log_report import Log

from ..core.ml_formats import *

from ..code_generation.generic_processor import GenericProcessor
from ..core.target import TargetRegister
from ..targets import *
from ..code_generation.code_constant import *

# populating target_map
target_map = {}
target_map["none"] = GenericProcessor
for target_name in TargetRegister.target_map:
    target_map[target_name] = TargetRegister.get_target_by_name(target_name)(None)


precision_map = {
    "binary32": ML_Binary32, 
    "binary64": ML_Binary64, 
    "int32": ML_Int32, 
    "uint32": ML_UInt32,
    "int64":  ML_Int64,
    "uint64": ML_UInt64,
}

accuracy_map = {
    "faithful": ML_Faithful,
    "cr"      : ML_CorrectlyRounded,
}

language_map = {
  "c": C_Code,
  "opencl": OpenCL_Code,
  "gappa": Gappa_Code
}


## parse a string of character and convert it into
#  the corresponding ML_Format instance
#  @param precision_str string to convert
#  @return ML_Format intsance corresponding to the input string
def precision_parser(precision_str):
  if precision_str in precision_map:
    return precision_map[precision_str]
  else:
    fixed_format = ML_Custom_FixedPoint_Format.parse_from_string(precision_str)
    if fixed_format is None:
      return eval(precision_str)
    else:
      return fixed_format

def accuracy_parser(accuracy_str):
    if accuracy_str in accuracy_map:
        return accuracy_map[accuracy_str]
    else:
        return eval(accuracy_str)

def interval_parser(interval_str):
  return eval(interval_str)

class ArgDefault(object):
  def __init__(self, default_value, level = 0):
    self.default_value = default_value
    self.level = level

  def get_pair(self):
    return self.default_value, self.level
  def get_value(self):
    return self.default_value
  def get_level(self):
    return self.level

  @staticmethod
  def select(arg_list):
    arg_list = [ArgDefault(arg, -1) if not isinstance(arg, ArgDefault) else arg for arg in arg_list]
    return min(arg_list, key = lambda v: v.get_level())

  @staticmethod
  def select_value(arg_list):
    return ArgDefault.select(arg_list).get_value()



## new argument template based on argparse module
class ML_NewArgTemplate(object):
  def __init__(self, default_function_name, default_output_file = "ml_func_gen.c"):
    self.default_output_file = default_output_file
    self.default_function_name = default_function_name

    self.parser = argparse.ArgumentParser(" Metalibm %s function generation script" % self.default_function_name)
    self.parser.add_argument("--libm", dest = "libm_compliant", action = "store_const", const = True, default = ArgDefault(False), help = "generate libm compliante code")
    self.parser.add_argument("--debug", dest = "debug", action = "store_const", const = True, default = ArgDefault(False), help = "enable debug display in generated code")
    self.parser.add_argument("--target", dest = "target_name", action = "store", default = "none", help = "select generation target")
    self.parser.add_argument("--disable-fma", dest = "fuse_fma", action = "store_const", const = False, default = ArgDefault(True), help = "disable FMA-like operation fusion")
    self.parser.add_argument("--output", action = "store", dest = "output_file", default = ArgDefault(self.default_output_file), help = "set output file")
    self.parser.add_argument("--fname", dest = "function_name", default = ArgDefault(self.default_function_name), help = "set function name")
    self.parser.add_argument("--precision", dest = "precision_name", default = ArgDefault("binary32"), help = "select main precision")
    self.parser.add_argument("--accuracy", dest = "accuracy_value", default = ArgDefault("faithful"), help = "select accuracy")
    self.parser.add_argument("--no-fpe", dest = "fast_path_extract", action = "store_const", const = False, default = ArgDefault(True), help = "disable Fast Path Extraction")
    self.parser.add_argument("--dot-product", dest = "dot_product_enabled", action = "store_const", const = True, default = ArgDefault(False), help = "enable Dot Product fusion")
    self.parser.add_argument ("--display-after-opt", dest = "display_after_opt", action = "store_const", const = True, default = ArgDefault(False), help = "display MDL IR after optimization")
    self.parser.add_argument ("--display-after-gen", dest = "display_after_gen", action = "store_const", const = True, default = ArgDefault(False), help = "display MDL IR after implementation generation")
    self.parser.add_argument("--input-interval", dest = "input_interval_str", default = ArgDefault("Interval(0,1)"), help = "select input range")
    self.parser.add_argument("--vector-size", dest = "vector_size" , default = ArgDefault("1"), help = "define size of vector (1: scalar implemenation)")
    self.parser.add_argument("--language", dest = "language_name", default = ArgDefault("c"), help = "select language for generated source code") 

    self.parser.add_argument("--auto-test", dest = "auto_test", action = "store", nargs = '?', const=10, type=int, default = ArgDefault(False), help = "enable the generation of a self-testing numerical/functionnal bench")
    self.parser.add_argument("--auto-test-execute", dest = "auto_test_execute", action = "store", nargs = '?', const=10, type=int, default = ArgDefault(False), help = "enable the generation of a self-testing numerical/functionnal bench")
    self.parser.add_argument("--auto-test-range", dest = "auto_test_range", action = "store", type=interval_parser, default = ArgDefault(Interval(-1,1)), help = "enable the generation of a self-testing numerical/functionnal bench")

    self.parser.add_argument("--verbose", dest = "verbose_enable", action = "store_const", const = True, default = ArgDefault(False), help = "enable Verbose log level")
    self.parser.add_argument("--target-info", dest = "target_info_flag", action = "store_const", const = True, default = ArgDefault(False), help = "display list of supported targets")

    self.parser.add_argument("--exception-error", dest = "exception_on_error", action = "store_const", const = True, default = ArgDefault(False), help = "convert Fatal error to python Exception rather than straight sys exit")
    self.parser.add_argument("--auto-test-std", dest = "auto_test_std", action = "store_const", const = True, default = ArgDefault(False), help = "enabling function test on standard test case list")


  ## parse command line arguments
  #  @p exit_on_info trigger early exit when info options is encountered
  def arg_extraction(self, exit_on_info = True):
    self.args = self.parser.parse_args(sys.argv[1:])
    if self.args.exception_on_error:
      Log.exit_on_error = False
    if self.args.verbose_enable is True:
      Log.enable_level(Log.Verbose)

    if self.args.target_info_flag is True:
      spacew = max(len(v) for v in target_map)
      for target_name in target_map:
        print "%s: %s %s " % (target_name, " " * (spacew - len(target_name)), target_map[target_name])
      if exit_on_info: 
        sys.exit(0)
        return None

    ## specific argument post-processing
    self.args.accuracy        = self.process_arg(self.args.accuracy_value , accuracy_parser)
    self.args.target          = self.process_arg(self.args.target_name, lambda v: target_map[v]())
    self.args.precision       = self.process_arg(self.args.precision_name, lambda v: precision_map[v])
    self.args.input_interval  = self.process_arg(self.args.input_interval_str, interval_parser)
    self.args.language        = self.process_arg(self.args.language_name, lambda v: language_map[v])
    self.args.vector_size     = self.process_arg(self.args.vector_size, int)

    return self.args

  ## process argument to return overloadable arg_value
  #  @p arg_value argument value (bare or encapsulated within an ArgDefault object)
  #  @p processing function to pre-process argument value
  def process_arg(self, arg_value, processing = lambda v: v):
    if isinstance(arg_value, ArgDefault):
      value = arg_value.get_value()
      level = arg_value.get_level()
    else:
      value = arg_value
      level = -1
    return ArgDefault(processing(value), level)


class ML_ArgTemplate(object):
  def __init__(self, default_output_file, default_function_name):
    self.default_output_file = default_output_file
    self.default_function_name = default_function_name
    self.help_map = {}
    self.parse_arg = [0]

  ## standard argument extraction from command line and storing, 
  #  Plus standard argument help and default value declaration
  def sys_arg_extraction(self, parse_arg = None, exit_on_info = True, check = True):
    # argument extraction 
    parse_arg = self.parse_arg if parse_arg is None else parse_arg
    self.libm_compliant  = test_flag_option("--libm", True, False, parse_arg = parse_arg, help_map = self.help_map, help_str = "enable libm compliance") 
    self.debug_flag      = test_flag_option("--debug", True, False, parse_arg = parse_arg, help_map = self.help_map, help_str = "enable debug display in generated code")
    target_name     = extract_option_value("--target", "none", parse_arg = parse_arg, help_map = self.help_map, help_str = "select target")
    self.fuse_fma        = test_flag_option("--disable-fma", False, True, parse_arg = parse_arg, help_map = self.help_map, help_str = "disable FMA fusion")
    self.output_file     = extract_option_value("--output", self.default_output_file, parse_arg = parse_arg, help_map = self.help_map, help_str = "set output file")
    self.function_name   = extract_option_value("--fname", self.default_function_name, parse_arg = parse_arg, help_map = self.help_map, help_str = "set function name")
    precision_name  = extract_option_value("--precision", "binary32", parse_arg = parse_arg, help_map = self.help_map, help_str = "select main precision")
    accuracy_value  = extract_option_value("--accuracy", "faithful", parse_arg = parse_arg, processing = accuracy_parser, help_map = self.help_map, help_str = "select accuracy")
    self.fast_path       = test_flag_option("--no-fpe", False, True, parse_arg = parse_arg, help_map = self.help_map, help_str = "disable Fast Path Extraction")
    self.dot_product_enabled = test_flag_option("--dot-product", True, False, parse_arg = parse_arg, help_map = self.help_map, help_str = "enable Dot Product fusion")
    self.display_after_opt = test_flag_option("--display-after-opt", True, False, parse_arg = parse_arg, help_map = self.help_map, help_str = "display MDL IR after optimization")
    self.display_after_gen = test_flag_option("--display-after-gen", True, False, parse_arg = parse_arg, help_map = self.help_map, help_str = "display MDL IR after implementation generation")
    input_interval = extract_option_value("--input-interval", "Interval(0,1)", parse_arg = parse_arg, processing = interval_parser, help_map = self.help_map, help_str = "select input range")
    self.vector_size = extract_option_value("--vector-size", "1", parse_arg = parse_arg, processing = lambda v: int(v), help_map = self.help_map, help_str = "define size of vector (1: scalar implemenation)")
    self.language = extract_option_value("--language", "c", parse_arg = parse_arg, processing = lambda v: language_map[v], help_map = self.help_map, help_str = "select language for generated source code") 

    self.auto_test = test_flag_option("--auto-test", True, False, parse_arg = parse_arg, help_map = self.help_map, help_str = "enable the generation of a self-testing numerical/functionnal bench")

    verbose_enable = test_flag_option("--verbose", True, False, parse_arg = parse_arg, help_map = self.help_map, help_str = "enable Verbose log level")

    exception_on_error = test_flag_option("--exception-error", True, False, parse_arg = parse_arg, help_map = self.help_map, help_str = "convert Fatal error to python Exception rather than straight sys exit")

    if exception_on_error:
      Log.exit_on_error = False
    if verbose_enable:
      Log.enable_level(Log.Verbose)

    self.accuracy        = accuracy_value
    self.target          = target_map[target_name]()
    self.precision       = precision_map[precision_name]
    self.input_interval  = input_interval
  
    if check:
      self.check_args(parse_arg, exit_on_info)
    
    return parse_arg

  def test_flag_option(self, *args, **kwords):
    return test_flag_option(*args, help_map = self.help_map, **kwords)

  def extract_option_value(self, *args, **kwords):
    return extract_option_value(*args, help_map = self.help_map, **kwords)

  def display_help(self):
    spacew = max(len(o) for o in self.help_map)
    print "option list:"
    for option_name in self.help_map:
      print "  %s %s %s" % (option_name, " " * (spacew - len(option_name)), self.help_map[option_name])

  def check_args(self, parse_arg, exit_on_info = True):
    """ check that all options on command line have been parse
        and display info messages """
    help_flag = test_flag_option("--help", True, False, parse_arg = parse_arg, help_map = self.help_map, help_str = "display this message")
    target_info_flag = test_flag_option("--target-info", True, False, parse_arg = parse_arg, help_map = self.help_map, help_str = "display the list of supported targets")
    for i in xrange(1, len(sys.argv)):
      if not i in parse_arg:
        self.display_help()
        Log.report(Log.Error, "unknown command line argument: %s" % sys.argv[i])
    if help_flag:
      self.display_help()
      if exit_on_info: 
        sys.exit(0)
        return None
    if target_info_flag:
      spacew = max(len(v) for v in target_map)
      for target_name in target_map:
        print "%s: %s %s " % (target_name, " " * (spacew - len(target_name)), target_map[target_name])
      if exit_on_info: 
        sys.exit(0)
        return None


if __name__ == "__main__":
    for target_name in target_map:
        print target_name, ": ", target_map[target_name]
