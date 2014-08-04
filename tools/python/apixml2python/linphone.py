# Copyright (C) 2014 Belledonne Communications SARL
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.


import sys


def strip_leading_linphone(s):
	if s.lower().startswith('linphone'):
		return s[8:]
	else:
		return s

def compute_event_name(s):
	s = strip_leading_linphone(s)
	s = s[4:-2] # Remove leading 'Core' and tailing 'Cb'
	event_name = ''
	first = True
	for l in s:
		if l.isupper() and not first:
			event_name += '_'
		event_name += l.lower()
		first = False
	return event_name


class MethodDefinition:
	def __init__(self, linphone_module, class_, method_node = None):
		self.body = ''
		self.arg_names = []
		self.parse_tuple_format = ''
		self.build_value_format = ''
		self.return_type = 'void'
		self.return_complete_type = 'void'
		self.method_node = method_node
		self.class_ = class_
		self.linphone_module = linphone_module
		self.self_arg = None
		self.xml_method_return = None
		self.xml_method_args = []
		self.method_type = 'instancemethod'

	def format_local_variables_definition(self):
		body = ''
		if self.xml_method_return is not None:
			self.return_type = self.xml_method_return.get('type')
			self.return_complete_type = self.xml_method_return.get('completetype')
		if self.return_complete_type != 'void':
			body += "\t" + self.return_complete_type + " cresult;\n"
			self.build_value_format = self.ctype_to_python_format(self.return_type, self.return_complete_type)
			if self.build_value_format == 'O':
				body += "\tPyObject * pyresult;\n"
			body += "\tPyObject * pyret;\n"
		if self.self_arg is not None:
			body += "\t" + self.self_arg.get('completetype') + "native_ptr;\n"
		for xml_method_arg in self.xml_method_args:
			arg_name = "_" + xml_method_arg.get('name')
			arg_type = xml_method_arg.get('type')
			arg_complete_type = xml_method_arg.get('completetype')
			fmt = self.ctype_to_python_format(arg_type, arg_complete_type)
			self.parse_tuple_format += fmt
			if fmt == 'O':
				body += "\tPyObject * " + arg_name + ";\n"
				body += "\t" + arg_complete_type + " " + arg_name + "_native_ptr;\n"
			elif strip_leading_linphone(arg_complete_type) in self.linphone_module.enum_names:
				body += "\tint " + arg_name + ";\n"
			else:
				body += "\t" + arg_complete_type + " " + arg_name + ";\n"
			self.arg_names.append(arg_name)
		return body

	def format_arguments_parsing(self):
		class_native_ptr_check_code = ''
		if self.self_arg is not None:
			class_native_ptr_check_code = self.format_class_native_pointer_check(False)
		parse_tuple_code = ''
		if len(self.arg_names) > 0:
			parse_tuple_code = \
"""	if (!PyArg_ParseTuple(args, "{fmt}", {args})) {{
		return NULL;
	}}
""".format(fmt=self.parse_tuple_format, args=', '.join(map(lambda a: '&' + a, self.arg_names)))
		return \
"""	{class_native_ptr_check_code}
	{parse_tuple_code}
	{args_native_ptr_check_code}
""".format(class_native_ptr_check_code=class_native_ptr_check_code,
		parse_tuple_code=parse_tuple_code,
		args_native_ptr_check_code=self.format_args_native_pointer_check())

	def format_enter_trace(self):
		fmt = ''
		args = []
		if self.self_arg is not None:
			fmt += "%p [%p]"
			args += ["self", "native_ptr"]
		for xml_method_arg in self.xml_method_args:
			arg_name = "_" + xml_method_arg.get('name')
			arg_type = xml_method_arg.get('type')
			arg_complete_type = xml_method_arg.get('completetype')
			if fmt != '':
				fmt += ', '
			f, a = self.ctype_to_str_format(arg_name, arg_type, arg_complete_type)
			fmt += f
			args += a
		args=', '.join(args)
		if args != '':
			args = ', ' + args
		return "\tpylinphone_trace(1, \"[PYLINPHONE] >>> %s({fmt})\", __FUNCTION__{args});\n".format(fmt=fmt, args=args)

	def format_c_function_call(self):
		arg_names = []
		for xml_method_arg in self.xml_method_args:
			arg_name = "_" + xml_method_arg.get('name')
			arg_type = xml_method_arg.get('type')
			arg_complete_type = xml_method_arg.get('completetype')
			type_str, checkfunc, convertfunc = self.ctype_to_python_type(arg_type, arg_complete_type)
			if convertfunc is None:
				arg_names.append(arg_name + "_native_ptr")
			else:
				arg_names.append(arg_name)
		body = "\t"
		if self.return_type != 'void':
			body += "cresult = "
		body += self.method_node.get('name') + "("
		if self.self_arg is not None:
			body += "native_ptr"
			if len(arg_names) > 0:
				body += ', '
		body += ', '.join(arg_names) + ");\n"
		return_from_user_data_code = ''
		new_from_native_pointer_code = ''
		ref_native_pointer_code = ''
		build_value_code = ''
		result_variable = ''
		if self.return_complete_type != 'void':
			if self.build_value_format == 'O':
				stripped_return_type = strip_leading_linphone(self.return_type)
				return_type_class = self.find_class_definition(self.return_type)
				if return_type_class['class_has_user_data']:
					get_user_data_function = return_type_class['class_c_function_prefix'] + "get_user_data"
					return_from_user_data_code = \
"""	if ((cresult != NULL) && ({func}(cresult) != NULL)) {{
		return (PyObject *){func}(cresult);
	}}
""".format(func=get_user_data_function)
				new_from_native_pointer_code = "\tpyresult = pylinphone_{return_type}_new_from_native_ptr(&pylinphone_{return_type}Type, cresult);\n".format(return_type=stripped_return_type)
				if self.self_arg is not None and return_type_class['class_refcountable']:
					ref_function = return_type_class['class_c_function_prefix'] + "ref"
					ref_native_pointer_code = "\t{func}(({cast_type})cresult);\n".format(func=ref_function, cast_type=self.remove_const_from_complete_type(self.return_complete_type))
				result_variable = 'pyresult'
			else:
				result_variable = 'cresult'
		if result_variable != '':
			build_value_code = "pyret = Py_BuildValue(\"{fmt}\", {result_variable});\n".format(fmt=self.build_value_format, result_variable=result_variable)
		body += \
"""	{return_from_user_data_code}
	{new_from_native_pointer_code}
	{ref_native_pointer_code}
	{build_value_code}
""".format(return_from_user_data_code=return_from_user_data_code,
		new_from_native_pointer_code=new_from_native_pointer_code,
		ref_native_pointer_code=ref_native_pointer_code,
		build_value_code=build_value_code)
		return body

	def format_return_trace(self):
		if self.return_complete_type != 'void':
			return "\tpylinphone_trace(-1, \"[PYLINPHONE] <<< %s -> %p\", __FUNCTION__, pyret);\n"
		else:
			return "\tpylinphone_trace(-1, \"[PYLINPHONE] <<< %s -> None\", __FUNCTION__);\n"

	def format_return_result(self):
		if self.return_complete_type != 'void':
			if self.build_value_format == 'O':
				return \
"""	Py_DECREF(pyresult);
	return pyret;"""
			else:
				return "\treturn pyret;"
		return "\tPy_RETURN_NONE;"

	def format_return_none_trace(self):
		return "\tpylinphone_trace(-1, \"[PYLINPHONE] <<< %s -> None\", __FUNCTION__);\n"

	def format_class_native_pointer_check(self, return_int):
		return_value = "NULL"
		if return_int:
			return_value = "-1"
		return \
"""	native_ptr = pylinphone_{class_name}_get_native_ptr(self);
	if (native_ptr == NULL) {{
		PyErr_SetString(PyExc_TypeError, "Invalid linphone.{class_name} instance");
		return {return_value};
	}}
""".format(class_name=self.class_['class_name'], return_value=return_value)

	def format_args_native_pointer_check(self):
		body = ''
		for xml_method_arg in self.xml_method_args:
			arg_name = "_" + xml_method_arg.get('name')
			arg_type = xml_method_arg.get('type')
			arg_complete_type = xml_method_arg.get('completetype')
			fmt = self.ctype_to_python_format(arg_type, arg_complete_type)
			if fmt == 'O':
				body += \
"""	if (({arg_name}_native_ptr = pylinphone_{arg_type}_get_native_ptr({arg_name})) == NULL) {{
		return NULL;
	}}
""".format(arg_name=arg_name, arg_type=strip_leading_linphone(arg_type))
		return body

	def parse_method_node(self):
		if self.method_node is not None:
			self.xml_method_return = self.method_node.find('./return')
			self.xml_method_args = self.method_node.findall('./arguments/argument')
			self.method_type = self.method_node.tag
		if self.method_type != 'classmethod' and len(self.xml_method_args) > 0:
			self.self_arg = self.xml_method_args[0]
			self.xml_method_args = self.xml_method_args[1:]

	def remove_const_from_complete_type(self, complete_type):
		splitted_type = complete_type.split(' ')
		while 'const' in splitted_type:
			splitted_type.remove('const')
		return ' '.join(splitted_type)

	def ctype_to_str_format(self, name, basic_type, complete_type, with_native_ptr=True):
		splitted_type = complete_type.split(' ')
		if basic_type == 'char':
			if '*' in splitted_type:
				return ('\\"%s\\"', [name])
			elif 'unsigned' in splitted_type:
				return ('%08x', [name])
		elif basic_type == 'int':
			# TODO:
			return ('%d', [name])
		elif basic_type == 'int8_t':
			return ('%d', [name])
		elif basic_type == 'uint8_t':
			return ('%u', [name])
		elif basic_type == 'int16_t':
			return ('%d', [name])
		elif basic_type == 'uint16_t':
			return ('%u', [name])
		elif basic_type == 'int32_t':
			return ('%d', [name])
		elif basic_type == 'uint32_t':
			return ('%u', [name])
		elif basic_type == 'int64_t':
			return ('%ld', [name])
		elif basic_type == 'uint64_t':
			return ('%lu', [name])
		elif basic_type == 'size_t':
			return ('%lu', [name])
		elif basic_type == 'float':
			return ('%f', [name])
		elif basic_type == 'double':
			return ('%f', [name])
		elif basic_type == 'bool_t':
			return ('%d', [name])
		else:
			if strip_leading_linphone(basic_type) in self.linphone_module.enum_names:
				return ('%d', [name])
			elif with_native_ptr:
				return ('%p [%p]', [name, name + "_native_ptr"])
			else:
				return ('%p', [name])

	def ctype_to_python_format(self, basic_type, complete_type):
		splitted_type = complete_type.split(' ')
		if basic_type == 'char':
			if '*' in splitted_type:
				return 'z'
			elif 'unsigned' in splitted_type:
				return 'b'
		elif basic_type == 'int':
			# TODO:
			return 'i'
		elif basic_type == 'int8_t':
			return 'c'
		elif basic_type == 'uint8_t':
			return 'b'
		elif basic_type == 'int16_t':
			return 'h'
		elif basic_type == 'uint16_t':
			return 'H'
		elif basic_type == 'int32_t':
			return 'l'
		elif basic_type == 'uint32_t':
			return 'k'
		elif basic_type == 'int64_t':
			return 'L'
		elif basic_type == 'uint64_t':
			return 'K'
		elif basic_type == 'size_t':
			return 'n'
		elif basic_type == 'float':
			return 'f'
		elif basic_type == 'double':
			return 'd'
		elif basic_type == 'bool_t':
			return 'i'
		else:
			if strip_leading_linphone(basic_type) in self.linphone_module.enum_names:
				return 'i'
			else:
				return 'O'

	def ctype_to_python_type(self, basic_type, complete_type):
		splitted_type = complete_type.split(' ')
		if basic_type == 'char':
			if '*' in splitted_type:
				return ('string', 'PyString_Check', 'PyString_AsString')
			else:
				return ('int', 'PyInt_Check', 'PyInt_AsLong')
		elif basic_type == 'int':
			if 'unsigned' in splitted_type:
				return ('unsigned int', 'PyLong_Check', 'PyLong_AsUnsignedLong')
			else:
				return ('int', 'PyLong_Check', 'PyLong_AsLong')
		elif basic_type in ['int8_t', 'int16_t' 'int32_t']:
			return ('int', 'PyLong_Check', 'PyLong_AsLong')
		elif basic_type in ['uint8_t', 'uin16_t', 'uint32_t']:
			return ('unsigned int', 'PyLong_Check', 'PyLong_AsUnsignedLong')
		elif basic_type == 'int64_t':
			return ('64bits int', 'PyLong_Check', 'PyLong_AsLongLong')
		elif basic_type == 'uint64_t':
			return ('64bits unsigned int', 'PyLong_Check', 'PyLong_AsUnsignedLongLong')
		elif basic_type == 'size_t':
			return ('size_t', 'PyLong_Check', 'PyLong_AsSsize_t')
		elif basic_type in ['float', 'double']:
			return ('float', 'PyFloat_Check', 'PyFloat_AsDouble')
		elif basic_type == 'bool_t':
			return ('bool', 'PyBool_Check', 'PyInt_AsLong')
		else:
			if strip_leading_linphone(basic_type) in self.linphone_module.enum_names:
				return ('int', 'PyInt_Check', 'PyInt_AsLong')
			else:
				return (None, None, None)

	def find_class_definition(self, basic_type):
		basic_type = strip_leading_linphone(basic_type)
		for c in self.linphone_module.classes:
			if c['class_name'] == basic_type:
				return c
		return None

	def format(self):
		self.parse_method_node()
		body = self.format_local_variables_definition()
		body += self.format_arguments_parsing()
		body += self.format_enter_trace()
		body += self.format_c_function_call()
		body += self.format_return_trace()
		body += self.format_return_result()
		return body

class NewMethodDefinition(MethodDefinition):
	def __init__(self, linphone_module, class_, method_node = None):
		MethodDefinition.__init__(self, linphone_module, class_, method_node)

	def format_local_variables_definition(self):
		return "\tpylinphone_{class_name}Object *self = (pylinphone_{class_name}Object *)type->tp_alloc(type, 0);\n".format(class_name=self.class_['class_name'])

	def format_arguments_parsing(self):
		return ''

	def format_enter_trace(self):
		return "\tpylinphone_trace(1, \"[PYLINPHONE] >>> %s()\", __FUNCTION__);\n"

	def format_c_function_call(self):
		return "\tself->native_ptr = NULL;\n"

	def format_return_trace(self):
		return "\tpylinphone_trace(-1, \"[PYLINPHONE] <<< %s -> %p\", __FUNCTION__, self);\n"

	def format_return_result(self):
		return "\treturn (PyObject *)self;"

class NewFromNativePointerMethodDefinition(MethodDefinition):
	def __init__(self, linphone_module, class_):
		MethodDefinition.__init__(self, linphone_module, class_, None)

	def format_local_variables_definition(self):
		return "\tpylinphone_{class_name}Object *self;\n".format(class_name=self.class_['class_name'])

	def format_arguments_parsing(self):
		return ''

	def format_enter_trace(self):
		return "\tpylinphone_trace(1, \"[PYLINPHONE] >>> %s(%p)\", __FUNCTION__, native_ptr);\n"

	def format_c_function_call(self):
		set_user_data_func_call = ''
		if self.class_['class_has_user_data']:
			set_user_data_func_call = "\t{function_prefix}set_user_data(self->native_ptr, self);\n".format(function_prefix=self.class_['class_c_function_prefix'])
		return \
"""	if (native_ptr == NULL) {{
	{none_trace}
		Py_RETURN_NONE;
	}}
	self = (pylinphone_{class_name}Object *)PyObject_New(pylinphone_{class_name}Object, type);
	if (self == NULL) {{
	{none_trace}
		Py_RETURN_NONE;
	}}
	self->native_ptr = ({class_cname} *)native_ptr;
	{set_user_data_func_call}
""".format(class_name=self.class_['class_name'], class_cname=self.class_['class_cname'],
		none_trace=self.format_return_none_trace(), set_user_data_func_call=set_user_data_func_call)

	def format_return_trace(self):
		return "\tpylinphone_trace(-1, \"[PYLINPHONE] <<< %s -> %p\", __FUNCTION__, self);\n"

	def format_return_result(self):
		return "\treturn (PyObject *)self;"

class DeallocMethodDefinition(MethodDefinition):
	def __init__(self, linphone_module, class_, method_node = None):
		MethodDefinition.__init__(self, linphone_module, class_, method_node)

	def format_local_variables_definition(self):
		func = "pylinphone_{class_name}_get_native_ptr".format(class_name=self.class_['class_name'])
		return \
"""	{arg_type} * native_ptr = {func}(self);
""".format(arg_type=self.class_['class_cname'], func=func)

	def format_arguments_parsing(self):
		return ''

	def format_enter_trace(self):
		return "\tpylinphone_trace(1, \"[PYLINPHONE] >>> %s(%p [%p])\", __FUNCTION__, self, native_ptr);\n"

	def format_c_function_call(self):
		# Increment the refcount on self to prevent reentrancy in the dealloc method.
		native_ptr_dealloc_code = "\tPy_INCREF(self);\n"
		if self.class_['class_refcountable']:
			native_ptr_dealloc_code += \
"""	if (native_ptr != NULL) {{
		{function_prefix}unref(native_ptr);
	}}
""".format(function_prefix=self.class_['class_c_function_prefix'])
		elif self.class_['class_destroyable']:
			native_ptr_dealloc_code += \
"""	if (native_ptr != NULL) {{
		{function_prefix}destroy(native_ptr);
	}}
""".format(function_prefix=self.class_['class_c_function_prefix'])
		return \
"""{native_ptr_dealloc_code}
	self->ob_type->tp_free(self);
""".format(native_ptr_dealloc_code=native_ptr_dealloc_code)

	def format_return_trace(self):
		return "\tpylinphone_trace(-1, \"[PYLINPHONE] <<< %s\", __FUNCTION__);"

	def format_return_result(self):
		return ''

class GetterMethodDefinition(MethodDefinition):
	def __init__(self, linphone_module, class_, method_node = None):
		MethodDefinition.__init__(self, linphone_module, class_, method_node)

class SetterMethodDefinition(MethodDefinition):
	def __init__(self, linphone_module, class_, method_node = None):
		MethodDefinition.__init__(self, linphone_module, class_, method_node)

	def format_arguments_parsing(self):
		if self.checkfunc is None:
			attribute_type_check_code = \
"""if (!PyObject_IsInstance(value, (PyObject *)&pylinphone_{class_name}Type)) {{
		PyErr_SetString(PyExc_TypeError, "The {attribute_name} attribute value must be a linphone.{class_name} instance");
		return -1;
	}}
""".format(class_name=self.first_arg_class, attribute_name=self.attribute_name)
		else:
			checknotnone = ''
			if self.type_str == 'string':
				checknotnone = "(value != Py_None) && "
			attribute_type_check_code = \
"""if ({checknotnone}!{checkfunc}(value)) {{
		PyErr_SetString(PyExc_TypeError, "The {attribute_name} attribute value must be a {type_str}");
		return -1;
	}}
""".format(checknotnone=checknotnone, checkfunc=self.checkfunc, attribute_name=self.attribute_name, type_str=self.type_str)
		if self.convertfunc is None:
			attribute_conversion_code = "{arg_name} = value;\n".format(arg_name="_" + self.first_arg_name)
		else:
			attribute_conversion_code = "{arg_name} = ({arg_type}){convertfunc}(value);\n".format(
				arg_name="_" + self.first_arg_name, arg_type=self.first_arg_complete_type, convertfunc=self.convertfunc)
		attribute_native_ptr_check_code = ''
		if self.python_fmt == 'O':
			attribute_native_ptr_check_code = \
"""{arg_name}_native_ptr = pylinphone_{arg_class}_get_native_ptr({arg_name});
	if ({arg_name}_native_ptr == NULL) {{
		PyErr_SetString(PyExc_TypeError, "Invalid linphone.{arg_class} instance");
		return -1;
	}}
""".format(arg_name="_" + self.first_arg_name, arg_class=self.first_arg_class)
		return \
"""	{native_ptr_check_code}
	if (value == NULL) {{
		PyErr_SetString(PyExc_TypeError, "Cannot delete the {attribute_name} attribute");
		return -1;
	}}
	{attribute_type_check_code}
	{attribute_conversion_code}
	{attribute_native_ptr_check_code}
""".format(attribute_name=self.attribute_name,
		native_ptr_check_code=self.format_class_native_pointer_check(True),
		attribute_type_check_code=attribute_type_check_code,
		attribute_conversion_code=attribute_conversion_code,
		attribute_native_ptr_check_code=attribute_native_ptr_check_code)

	def format_c_function_call(self):
		use_native_ptr = ''
		if self.python_fmt == 'O':
			use_native_ptr = '_native_ptr'
		return "\t{method_name}(native_ptr, {arg_name}{use_native_ptr});\n".format(
			arg_name="_" + self.first_arg_name, method_name=self.method_node.get('name'), use_native_ptr=use_native_ptr)

	def format_return_trace(self):
		return "\tpylinphone_trace(-1, \"[PYLINPHONE] <<< %s -> 0\", __FUNCTION__);\n"

	def format_return_result(self):
		return "\treturn 0;"

	def parse_method_node(self):
		MethodDefinition.parse_method_node(self)
		# Force return value type of setter function to prevent declaring useless local variables
		# TODO: Investigate. Maybe we should decide that setters must always return an int value.
		self.xml_method_return = None
		self.attribute_name = self.method_node.get('property_name')
		self.first_arg_type = self.xml_method_args[0].get('type')
		self.first_arg_complete_type = self.xml_method_args[0].get('completetype')
		self.first_arg_name = self.xml_method_args[0].get('name')
		self.type_str, self.checkfunc, self.convertfunc = self.ctype_to_python_type(self.first_arg_type, self.first_arg_complete_type)
		self.first_arg_class = strip_leading_linphone(self.first_arg_type)
		self.python_fmt = self.ctype_to_python_format(self.first_arg_type, self.first_arg_complete_type)

class EventCallbackMethodDefinition(MethodDefinition):
	def __init__(self, linphone_module, class_, method_node = None):
		MethodDefinition.__init__(self, linphone_module, class_, method_node)

	def format_local_variables_definition(self):
		common = \
"""	pylinphone_CoreObject *pylc = (pylinphone_CoreObject *)linphone_core_get_user_data(lc);
	PyObject *func = PyDict_GetItemString(pylc->vtable_dict, "{name}");
	PyGILState_STATE pygil_state;""".format(name=self.class_['event_name'])
		specific = ''
		for xml_method_arg in self.xml_method_args:
			arg_name = 'py' + xml_method_arg.get('name')
			arg_type = xml_method_arg.get('type')
			arg_complete_type = xml_method_arg.get('completetype')
			fmt = self.ctype_to_python_format(arg_type, arg_complete_type)
			if fmt == 'O':
				specific += "\tPyObject * " + arg_name + " = NULL;\n"
		return "{common}\n{specific}".format(common=common, specific=specific)

	def format_arguments_parsing(self):
		body = "\tpygil_state = PyGILState_Ensure();\n"
		for xml_method_arg in self.xml_method_args:
			arg_name = xml_method_arg.get('name')
			arg_type = xml_method_arg.get('type')
			arg_complete_type = xml_method_arg.get('completetype')
			fmt = self.ctype_to_python_format(arg_type, arg_complete_type)
			if fmt == 'O':
				type_class = self.find_class_definition(arg_type)
				get_user_data_code = ''
				new_from_native_pointer_code = "py{name} = pylinphone_{arg_type}_new_from_native_ptr(&pylinphone_{arg_type}Type, {name});".format(name=arg_name, arg_type=strip_leading_linphone(arg_type))
				if type_class is not None and type_class['class_has_user_data']:
					get_user_data_function = type_class['class_c_function_prefix'] + "get_user_data"
					get_user_data_code = "py{name} = {get_user_data_function}({name});".format(name=arg_name, get_user_data_function=get_user_data_function)
				body += \
"""	{get_user_data_code}
	if (py{name} == NULL) {{
		{new_from_native_pointer_code}
	}}
""".format(name=arg_name, get_user_data_code=get_user_data_code, new_from_native_pointer_code=new_from_native_pointer_code)
		return body

	def format_enter_trace(self):
		fmt = '%p'
		args = ['lc']
		for xml_method_arg in self.xml_method_args:
			arg_name = xml_method_arg.get('name')
			arg_type = xml_method_arg.get('type')
			arg_complete_type = xml_method_arg.get('completetype')
			if fmt != '':
				fmt += ', '
			f, a = self.ctype_to_str_format(arg_name, arg_type, arg_complete_type, with_native_ptr=False)
			fmt += f
			args += a
		args=', '.join(args)
		if args != '':
			args = ', ' + args
		return "\tpylinphone_trace(1, \"[PYLINPHONE] >>> %s({fmt})\", __FUNCTION__{args});\n".format(fmt=fmt, args=args)

	def format_c_function_call(self):
		fmt = 'O'
		args = ['pylc']
		for xml_method_arg in self.xml_method_args:
			arg_name = xml_method_arg.get('name')
			arg_type = xml_method_arg.get('type')
			arg_complete_type = xml_method_arg.get('completetype')
			f = self.ctype_to_python_format(arg_type, arg_complete_type)
			fmt += f
			if f == 'O':
				args.append('py' + arg_name)
			else:
				args.append(arg_name)
		args=', '.join(args)
		return \
"""	if ((func != NULL) && PyFunction_Check(func)) {{
		if (PyEval_CallFunction(func, "{fmt}", {args}) == NULL) {{
			PyErr_Print();
		}}
	}}
""".format(fmt=fmt, args=args)

	def format_return_trace(self):
		return "\tpylinphone_trace(-1, \"[PYLINPHONE] <<< %s\", __FUNCTION__);\n"

	def format_return_result(self):
		return '\tPyGILState_Release(pygil_state);'

	def format(self):
		body = MethodDefinition.format(self)
		arguments = ['LinphoneCore * lc']
		for xml_method_arg in self.xml_method_args:
			arg_name = xml_method_arg.get('name')
			arg_type = xml_method_arg.get('type')
			arg_complete_type = xml_method_arg.get('completetype')
			arguments.append(arg_complete_type + ' ' + arg_name)
		definition = \
"""static void pylinphone_Core_callback_{event_name}({arguments}) {{
{body}
}}
""".format(event_name=self.class_['event_name'], arguments=', '.join(arguments), body=body)
		return definition


class LinphoneModule(object):
	def __init__(self, tree, blacklisted_classes, blacklisted_events, blacklisted_functions, hand_written_functions):
		self.internal_instance_method_names = ['destroy', 'ref', 'unref']
		self.internal_property_names = ['user_data']
		self.enums = []
		self.enum_names = []
		xml_enums = tree.findall("./enums/enum")
		for xml_enum in xml_enums:
			if xml_enum.get('deprecated') == 'true':
				continue
			e = {}
			e['enum_name'] = strip_leading_linphone(xml_enum.get('name'))
			e['enum_doc'] = self.__format_doc(xml_enum.find('briefdescription'), xml_enum.find('detaileddescription'))
			e['enum_values'] = []
			xml_enum_values = xml_enum.findall("./values/value")
			for xml_enum_value in xml_enum_values:
				if xml_enum_value.get('deprecated') == 'true':
					continue
				v = {}
				v['enum_value_cname'] = xml_enum_value.get('name')
				v['enum_value_name'] = strip_leading_linphone(v['enum_value_cname'])
				e['enum_values'].append(v)
			self.enums.append(e)
			self.enum_names.append(e['enum_name'])
		self.events = []
		self.classes = []
		xml_classes = tree.findall("./classes/class")
		for xml_class in xml_classes:
			if xml_class.get('deprecated') == 'true':
				continue
			if xml_class.get('name') in blacklisted_classes:
				continue
			c = {}
			c['class_xml_node'] = xml_class
			c['class_cname'] = xml_class.get('name')
			c['class_name'] = strip_leading_linphone(c['class_cname'])
			c['class_c_function_prefix'] = xml_class.get('cfunctionprefix')
			c['class_doc'] = self.__format_doc(xml_class.find('briefdescription'), xml_class.find('detaileddescription'))
			c['class_refcountable'] = (xml_class.get('refcountable') == 'true')
			c['class_destroyable'] = (xml_class.get('destroyable') == 'true')
			c['class_has_user_data'] = False
			c['class_type_methods'] = []
			c['class_type_hand_written_methods'] = []
			c['class_object_members'] = ''
			if c['class_name'] == 'Core':
				c['class_object_members'] = "\tPyObject *vtable_dict;"
				xml_events = xml_class.findall("./events/event")
				for xml_event in xml_events:
					if xml_event.get('deprecated') == 'true':
						continue
					if xml_event.get('name') in blacklisted_events:
						  continue
					ev = {}
					ev['event_xml_node'] = xml_event
					ev['event_cname'] = xml_event.get('name')
					ev['event_name'] = compute_event_name(ev['event_cname'])
					ev['event_doc'] = self.__format_doc(xml_event.find('briefdescription'), xml_event.find('detaileddescription'))
					self.events.append(ev)
			xml_type_methods = xml_class.findall("./classmethods/classmethod")
			for xml_type_method in xml_type_methods:
				if xml_type_method.get('deprecated') == 'true':
					continue
				method_name = xml_type_method.get('name')
				if method_name in blacklisted_functions:
					continue
				m = {}
				m['method_name'] = method_name.replace(c['class_c_function_prefix'], '')
				if method_name in hand_written_functions:
					c['class_type_hand_written_methods'].append(m)
				else:
					m['method_xml_node'] = xml_type_method
					c['class_type_methods'].append(m)
			c['class_instance_methods'] = []
			xml_instance_methods = xml_class.findall("./instancemethods/instancemethod")
			for xml_instance_method in xml_instance_methods:
				if xml_instance_method.get('deprecated') == 'true':
					continue
				method_name = xml_instance_method.get('name')
				if method_name in blacklisted_functions:
					continue
				method_name = method_name.replace(c['class_c_function_prefix'], '')
				if method_name in self.internal_instance_method_names:
					continue
				m = {}
				m['method_name'] = method_name
				m['method_xml_node'] = xml_instance_method
				c['class_instance_methods'].append(m)
			c['class_properties'] = []
			xml_properties = xml_class.findall("./properties/property")
			for xml_property in xml_properties:
				property_name = xml_property.get('name')
				if property_name == 'user_data':
					c['class_has_user_data'] = True
				if property_name in self.internal_property_names:
					continue
				p = {}
				p['property_name'] = property_name
				xml_property_getter = xml_property.find("./getter")
				xml_property_setter = xml_property.find("./setter")
				if xml_property_getter is not None and (
					xml_property_getter.get('name') in blacklisted_functions or xml_property_getter.get('deprecated') == 'true'):
					continue
				if xml_property_setter is not None and (
					xml_property_setter.get('name') in blacklisted_functions or xml_property_setter.get('deprecated') == 'true'):
					continue
				if xml_property_getter is not None:
					xml_property_getter.set('property_name', property_name)
					p['getter_name'] = xml_property_getter.get('name').replace(c['class_c_function_prefix'], '')
					p['getter_xml_node'] = xml_property_getter
					p['getter_reference'] = "(getter)pylinphone_" + c['class_name'] + "_" + p['getter_name']
					p['getter_definition_begin'] = "static PyObject * pylinphone_" + c['class_name'] + "_" + p['getter_name'] + "(PyObject *self, void *closure) {"
					p['getter_definition_end'] = "}"
				else:
					p['getter_reference'] = "NULL"
				if xml_property_setter is not None:
					xml_property_setter.set('property_name', property_name)
					p['setter_name'] = xml_property_setter.get('name').replace(c['class_c_function_prefix'], '')
					p['setter_xml_node'] = xml_property_setter
					p['setter_reference'] = "(setter)pylinphone_" + c['class_name'] + "_" + p['setter_name']
					p['setter_definition_begin'] = "static int pylinphone_" + c['class_name'] + "_" + p['setter_name'] + "(PyObject *self, PyObject *value, void *closure) {"
					p['setter_definition_end'] = "}"
				else:
					p['setter_reference'] = "NULL"
				c['class_properties'].append(p)
			self.classes.append(c)
		# Format events definitions
		for ev in self.events:
			ev['event_callback_definition'] = EventCallbackMethodDefinition(self, ev, ev['event_xml_node']).format()
			ev['event_vtable_reference'] = "_vtable.{name} = pylinphone_Core_callback_{name};".format(name=ev['event_name'])
		# Format methods' bodies
		for c in self.classes:
			xml_new_method = c['class_xml_node'].find("./classmethods/classmethod[@name='" + c['class_c_function_prefix'] + "new']")
			try:
				c['new_body'] = NewMethodDefinition(self, c, xml_new_method).format()
			except Exception, e:
				e.args += (c['class_name'], 'new_body')
				raise
			try:
				c['new_from_native_pointer_body'] = NewFromNativePointerMethodDefinition(self, c).format()
			except Exception, e:
				e.args += (c['class_name'], 'new_from_native_pointer_body')
				raise
			try:
				for m in c['class_type_methods']:
					m['method_body'] = MethodDefinition(self, c, m['method_xml_node']).format()
				for m in c['class_instance_methods']:
					m['method_body'] = MethodDefinition(self, c, m['method_xml_node']).format()
			except Exception, e:
				e.args += (c['class_name'], m['method_name'])
				raise
			try:
				for p in c['class_properties']:
					if p.has_key('getter_xml_node'):
						p['getter_body'] = GetterMethodDefinition(self, c, p['getter_xml_node']).format()
					if p.has_key('setter_xml_node'):
						p['setter_body'] = SetterMethodDefinition(self, c, p['setter_xml_node']).format()
			except Exception, e:
				e.args += (c['class_name'], p['property_name'])
				raise
			try:
				if c['class_refcountable']:
					xml_instance_method = c['class_xml_node'].find("./instancemethods/instancemethod[@name='" + c['class_c_function_prefix'] + "unref']")
					c['dealloc_body'] = DeallocMethodDefinition(self, c, xml_instance_method).format()
				elif c['class_destroyable']:
					xml_instance_method = c['class_xml_node'].find("./instancemethods/instancemethod[@name='" + c['class_c_function_prefix'] + "destroy']")
					c['dealloc_body'] = DeallocMethodDefinition(self, c, xml_instance_method).format()
				else:
					c['dealloc_body'] = DeallocMethodDefinition(self, c).format()
			except Exception, e:
				e.args += (c['class_name'], 'dealloc_body')
				raise

	def __format_doc_node(self, node):
		desc = ''
		if node.tag == 'para':
			if node.text is not None:
				desc += node.text.strip()
			for n in list(node):
				desc += self.__format_doc_node(n)
		elif node.tag == 'note':
			if node.text is not None:
				desc += node.text.strip()
			for n in list(node):
				desc += self.__format_doc_node(n)
		elif node.tag == 'ref':
			if node.text is not None:
				desc += ' ' + node.text.strip() + ' '
		tail = node.tail.strip()
		if tail != '':
			if node.tag != 'ref':
				desc += '\n'
			desc += tail
		if node.tag == 'para':
			desc += '\n'
		return desc

	def __format_doc(self, brief_description, detailed_description):
		doc = ''
		if brief_description is None:
			brief_description = ''
		if detailed_description is None:
			detailed_description = ''
		else:
			desc = ''
			for node in list(detailed_description):
				desc += self.__format_doc_node(node) + '\n'
			detailed_description = desc.strip().replace('\n', '\\n')
		brief_description = brief_description.strip()
		doc += brief_description
		if detailed_description != '':
			if doc != '':
				doc += '\\n\\n'
			doc+= detailed_description
		doc = '\"' + doc + '\"'
		return doc