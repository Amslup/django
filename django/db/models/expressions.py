import copy
import datetime

from django.conf import settings
from django.core.exceptions import FieldError
from django.db.backends import utils as backend_utils
from django.db.models import fields
from django.db.models.constants import LOOKUP_SEP
from django.db.models.query_utils import Q, refs_aggregate
from django.utils import six, timezone
from django.utils.functional import cached_property


class Combinable(object):
    """
    Provides the ability to combine one or two objects with
    some connector. For example F('foo') + F('bar').
    """

    # Arithmetic connectors
    ADD = '+'
    SUB = '-'
    MUL = '*'
    DIV = '/'
    POW = '^'
    # The following is a quoted % operator - it is quoted because it can be
    # used in strings that also have parameter substitution.
    MOD = '%%'

    # Bitwise operators - note that these are generated by .bitand()
    # and .bitor(), the '&' and '|' are reserved for boolean operator
    # usage.
    BITAND = '&'
    BITOR = '|'

    def _combine(self, other, connector, reversed, node=None):
        if not hasattr(other, 'resolve_expression'):
            # everything must be resolvable to an expression
            if isinstance(other, datetime.timedelta):
                other = DurationValue(other, output_field=fields.DurationField())
            else:
                other = Value(other)

        if reversed:
            return CombinedExpression(other, connector, self)
        return CombinedExpression(self, connector, other)

    #############
    # OPERATORS #
    #############

    def __add__(self, other):
        return self._combine(other, self.ADD, False)

    def __sub__(self, other):
        return self._combine(other, self.SUB, False)

    def __mul__(self, other):
        return self._combine(other, self.MUL, False)

    def __truediv__(self, other):
        return self._combine(other, self.DIV, False)

    def __div__(self, other):  # Python 2 compatibility
        return type(self).__truediv__(self, other)

    def __mod__(self, other):
        return self._combine(other, self.MOD, False)

    def __pow__(self, other):
        return self._combine(other, self.POW, False)

    def __and__(self, other):
        raise NotImplementedError(
            "Use .bitand() and .bitor() for bitwise logical operations."
        )

    def bitand(self, other):
        return self._combine(other, self.BITAND, False)

    def __or__(self, other):
        raise NotImplementedError(
            "Use .bitand() and .bitor() for bitwise logical operations."
        )

    def bitor(self, other):
        return self._combine(other, self.BITOR, False)

    def __radd__(self, other):
        return self._combine(other, self.ADD, True)

    def __rsub__(self, other):
        return self._combine(other, self.SUB, True)

    def __rmul__(self, other):
        return self._combine(other, self.MUL, True)

    def __rtruediv__(self, other):
        return self._combine(other, self.DIV, True)

    def __rdiv__(self, other):  # Python 2 compatibility
        return type(self).__rtruediv__(self, other)

    def __rmod__(self, other):
        return self._combine(other, self.MOD, True)

    def __rpow__(self, other):
        return self._combine(other, self.POW, True)

    def __rand__(self, other):
        raise NotImplementedError(
            "Use .bitand() and .bitor() for bitwise logical operations."
        )

    def __ror__(self, other):
        raise NotImplementedError(
            "Use .bitand() and .bitor() for bitwise logical operations."
        )


class BaseExpression(object):
    """
    Base class for all query expressions.
    """

    # aggregate specific fields
    is_summary = False

    def __init__(self, output_field=None):
        self._output_field = output_field

    def get_db_converters(self, connection):
        return [self.convert_value] + self.output_field.get_db_converters(connection)

    def get_source_expressions(self):
        return []

    def set_source_expressions(self, exprs):
        assert len(exprs) == 0

    def _parse_expressions(self, *expressions):
        return [
            arg if hasattr(arg, 'resolve_expression') else (
                F(arg) if isinstance(arg, six.string_types) else Value(arg)
            ) for arg in expressions
        ]

    def as_sql(self, compiler, connection):
        """
        Responsible for returning a (sql, [params]) tuple to be included
        in the current query.

        Different backends can provide their own implementation, by
        providing an `as_{vendor}` method and patching the Expression:

        ```
        def override_as_sql(self, compiler, connection):
            # custom logic
            return super(Expression, self).as_sql(compiler, connection)
        setattr(Expression, 'as_' + connection.vendor, override_as_sql)
        ```

        Arguments:
         * compiler: the query compiler responsible for generating the query.
           Must have a compile method, returning a (sql, [params]) tuple.
           Calling compiler(value) will return a quoted `value`.

         * connection: the database connection used for the current query.

        Returns: (sql, params)
          Where `sql` is a string containing ordered sql parameters to be
          replaced with the elements of the list `params`.
        """
        raise NotImplementedError("Subclasses must implement as_sql()")

    @cached_property
    def contains_aggregate(self):
        for expr in self.get_source_expressions():
            if expr and expr.contains_aggregate:
                return True
        return False

    @cached_property
    def contains_column_references(self):
        for expr in self.get_source_expressions():
            if expr and expr.contains_column_references:
                return True
        return False

    @cached_property
    def contributes_to_group_by(self):
        for expr in self.get_source_expressions():
            if expr and expr.contributes_to_group_by:
                return True
        return self.contains_column_references

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        """
        Provides the chance to do any preprocessing or validation before being
        added to the query.

        Arguments:
         * query: the backend query implementation
         * allow_joins: boolean allowing or denying use of joins
           in this query
         * reuse: a set of reusable joins for multijoins
         * summarize: a terminal aggregate clause
         * for_save: whether this expression about to be used in a save or update

        Returns: an Expression to be added to the query.
        """
        c = self.copy()
        c.is_summary = summarize
        c.set_source_expressions([
            expr.resolve_expression(query, allow_joins, reuse, summarize)
            for expr in c.get_source_expressions()
        ])
        return c

    def _prepare(self, field):
        """
        Hook used by Field.get_prep_lookup() to do custom preparation.
        """
        return self

    @property
    def field(self):
        return self.output_field

    @cached_property
    def output_field(self):
        """
        Returns the output type of this expressions.
        """
        if self._output_field_or_none is None:
            raise FieldError("Cannot resolve expression type, unknown output_field")
        return self._output_field_or_none

    @cached_property
    def _output_field_or_none(self):
        """
        Returns the output field of this expression, or None if no output type
        can be resolved. Note that the 'output_field' property will raise
        FieldError if no type can be resolved, but this attribute allows for
        None values.
        """
        if self._output_field is None:
            self._resolve_output_field()
        return self._output_field

    def _resolve_output_field(self):
        """
        Attempts to infer the output type of the expression. If the output
        fields of all source fields match then we can simply infer the same
        type here. This isn't always correct, but it makes sense most of the
        time.

        Consider the difference between `2 + 2` and `2 / 3`. Inferring
        the type here is a convenience for the common case. The user should
        supply their own output_field with more complex computations.

        If a source does not have an `_output_field` then we exclude it from
        this check. If all sources are `None`, then an error will be thrown
        higher up the stack in the `output_field` property.
        """
        if self._output_field is None:
            sources = self.get_source_fields()
            num_sources = len(sources)
            if num_sources == 0:
                self._output_field = None
            else:
                for source in sources:
                    if self._output_field is None:
                        self._output_field = source
                    if source is not None and not isinstance(self._output_field, source.__class__):
                        raise FieldError(
                            "Expression contains mixed types. You must set output_field")

    def convert_value(self, value, expression, connection, context):
        """
        Expressions provide their own converters because users have the option
        of manually specifying the output_field which may be a different type
        from the one the database returns.
        """
        field = self.output_field
        internal_type = field.get_internal_type()
        if value is None:
            return value
        elif internal_type == 'FloatField':
            return float(value)
        elif internal_type.endswith('IntegerField'):
            return int(value)
        elif internal_type == 'DecimalField':
            return backend_utils.typecast_decimal(value)
        return value

    def get_lookup(self, lookup):
        return self.output_field.get_lookup(lookup)

    def get_transform(self, name):
        return self.output_field.get_transform(name)

    def relabeled_clone(self, change_map):
        clone = self.copy()
        clone.set_source_expressions(
            [e.relabeled_clone(change_map) for e in self.get_source_expressions()])
        return clone

    def copy(self):
        c = copy.copy(self)
        c.copied = True
        return c

    def refs_aggregate(self, existing_aggregates):
        """
        Does this expression contain a reference to some of the
        existing aggregates? If so, returns the aggregate and also
        the lookup parts that *weren't* found. So, if
            existing_aggregates = {'max_id': Max('id')}
            self.name = 'max_id'
            queryset.filter(max_id__range=[10,100])
        then this method will return Max('id') and those parts of the
        name that weren't found. In this case `max_id` is found and the range
        portion is returned as ('range',).
        """
        for node in self.get_source_expressions():
            agg, lookup = node.refs_aggregate(existing_aggregates)
            if agg:
                return agg, lookup
        return False, ()

    def get_group_by_cols(self):
        if not self.contains_aggregate:
            return [self]
        cols = []
        for source in self.get_source_expressions():
            cols.extend(source.get_group_by_cols())
        return cols

    def get_source_fields(self):
        """
        Returns the underlying field types used by this
        aggregate.
        """
        return [e._output_field_or_none for e in self.get_source_expressions()]

    def asc(self):
        return OrderBy(self)

    def desc(self):
        return OrderBy(self, descending=True)

    def reverse_ordering(self):
        return self

    def flatten(self):
        """
        Recursively yield this expression and all subexpressions, in
        depth-first order.
        """
        yield self
        for expr in self.get_source_expressions():
            if expr:
                for inner_expr in expr.flatten():
                    yield inner_expr


class Expression(BaseExpression, Combinable):
    """
    An expression that can be combined with other expressions.
    """
    pass


class CombinedExpression(Expression):

    def __init__(self, lhs, connector, rhs, output_field=None):
        super(CombinedExpression, self).__init__(output_field=output_field)
        self.connector = connector
        self.lhs = lhs
        self.rhs = rhs

    def __repr__(self):
        return "<{}: {}>".format(self.__class__.__name__, self)

    def __str__(self):
        return "{} {} {}".format(self.lhs, self.connector, self.rhs)

    def get_source_expressions(self):
        return [self.lhs, self.rhs]

    def set_source_expressions(self, exprs):
        self.lhs, self.rhs = exprs

    def as_sql(self, compiler, connection):
        try:
            lhs_output = self.lhs.output_field
        except FieldError:
            lhs_output = None
        try:
            rhs_output = self.rhs.output_field
        except FieldError:
            rhs_output = None
        if (not connection.features.has_native_duration_field and
                ((lhs_output and lhs_output.get_internal_type() == 'DurationField')
                or (rhs_output and rhs_output.get_internal_type() == 'DurationField'))):
            return DurationExpression(self.lhs, self.connector, self.rhs).as_sql(compiler, connection)
        if (lhs_output and rhs_output and self.connector == self.SUB and
            lhs_output.get_internal_type() in {'DateField', 'DateTimeField', 'TimeField'} and
                lhs_output.get_internal_type() == lhs_output.get_internal_type()):
            return TemporalSubtraction(self.lhs, self.rhs).as_sql(compiler, connection)
        expressions = []
        expression_params = []
        sql, params = compiler.compile(self.lhs)
        expressions.append(sql)
        expression_params.extend(params)
        sql, params = compiler.compile(self.rhs)
        expressions.append(sql)
        expression_params.extend(params)
        # order of precedence
        expression_wrapper = '(%s)'
        sql = connection.ops.combine_expression(self.connector, expressions)
        return expression_wrapper % sql, expression_params

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        c = self.copy()
        c.is_summary = summarize
        c.lhs = c.lhs.resolve_expression(query, allow_joins, reuse, summarize, for_save)
        c.rhs = c.rhs.resolve_expression(query, allow_joins, reuse, summarize, for_save)
        return c


class DurationExpression(CombinedExpression):
    def compile(self, side, compiler, connection):
        if not isinstance(side, DurationValue):
            try:
                output = side.output_field
            except FieldError:
                pass
            else:
                if output.get_internal_type() == 'DurationField':
                    sql, params = compiler.compile(side)
                    return connection.ops.format_for_duration_arithmetic(sql), params
        return compiler.compile(side)

    def as_sql(self, compiler, connection):
        connection.ops.check_expression_support(self)
        expressions = []
        expression_params = []
        sql, params = self.compile(self.lhs, compiler, connection)
        expressions.append(sql)
        expression_params.extend(params)
        sql, params = self.compile(self.rhs, compiler, connection)
        expressions.append(sql)
        expression_params.extend(params)
        # order of precedence
        expression_wrapper = '(%s)'
        sql = connection.ops.combine_duration_expression(self.connector, expressions)
        return expression_wrapper % sql, expression_params


class TemporalSubtraction(CombinedExpression):
    def __init__(self, lhs, rhs):
        super(TemporalSubtraction, self).__init__(lhs, self.SUB, rhs, output_field=fields.DurationField())

    def as_sql(self, compiler, connection):
        connection.ops.check_expression_support(self)
        lhs = compiler.compile(self.lhs, connection)
        rhs = compiler.compile(self.rhs, connection)
        return connection.ops.subtract_temporals(self.lhs.output_field.get_internal_type(), lhs, rhs)


class F(Combinable):
    """
    An object capable of resolving references to existing query objects.
    """
    def __init__(self, name):
        """
        Arguments:
         * name: the name of the field this expression references
        """
        self.name = name

    def __repr__(self):
        return "{}({})".format(self.__class__.__name__, self.name)

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        return query.resolve_ref(self.name, allow_joins, reuse, summarize)

    def refs_aggregate(self, existing_aggregates):
        return refs_aggregate(self.name.split(LOOKUP_SEP), existing_aggregates)

    def asc(self):
        return OrderBy(self)

    def desc(self):
        return OrderBy(self, descending=True)


class Func(Expression):
    """
    A SQL function call.
    """
    function = None
    template = '%(function)s(%(expressions)s)'
    arg_joiner = ', '
    arity = None  # The number of arguments the function accepts.

    def __init__(self, *expressions, **extra):
        if self.arity is not None and len(expressions) != self.arity:
            raise TypeError(
                "'%s' takes exactly %s %s (%s given)" % (
                    self.__class__.__name__,
                    self.arity,
                    "argument" if self.arity == 1 else "arguments",
                    len(expressions),
                )
            )
        output_field = extra.pop('output_field', None)
        super(Func, self).__init__(output_field=output_field)
        self.source_expressions = self._parse_expressions(*expressions)
        self.extra = extra

    def __repr__(self):
        args = self.arg_joiner.join(str(arg) for arg in self.source_expressions)
        extra = ', '.join(str(key) + '=' + str(val) for key, val in self.extra.items())
        if extra:
            return "{}({}, {})".format(self.__class__.__name__, args, extra)
        return "{}({})".format(self.__class__.__name__, args)

    def get_source_expressions(self):
        return self.source_expressions

    def set_source_expressions(self, exprs):
        self.source_expressions = exprs

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        c = self.copy()
        c.is_summary = summarize
        for pos, arg in enumerate(c.source_expressions):
            c.source_expressions[pos] = arg.resolve_expression(query, allow_joins, reuse, summarize, for_save)
        return c

    def as_sql(self, compiler, connection, function=None, template=None):
        connection.ops.check_expression_support(self)
        sql_parts = []
        params = []
        for arg in self.source_expressions:
            arg_sql, arg_params = compiler.compile(arg)
            sql_parts.append(arg_sql)
            params.extend(arg_params)
        if function is None:
            self.extra['function'] = self.extra.get('function', self.function)
        else:
            self.extra['function'] = function
        self.extra['expressions'] = self.extra['field'] = self.arg_joiner.join(sql_parts)
        template = template or self.extra.get('template', self.template)
        return template % self.extra, params

    def as_sqlite(self, *args, **kwargs):
        sql, params = self.as_sql(*args, **kwargs)
        try:
            if self.output_field.get_internal_type() == 'DecimalField':
                sql = 'CAST(%s AS NUMERIC)' % sql
        except FieldError:
            pass
        return sql, params

    def copy(self):
        copy = super(Func, self).copy()
        copy.source_expressions = self.source_expressions[:]
        copy.extra = self.extra.copy()
        return copy


class Value(Expression):
    """
    Represents a wrapped value as a node within an expression
    """
    def __init__(self, value, output_field=None):
        """
        Arguments:
         * value: the value this expression represents. The value will be
           added into the sql parameter list and properly quoted.

         * output_field: an instance of the model field type that this
           expression will return, such as IntegerField() or CharField().
        """
        super(Value, self).__init__(output_field=output_field)
        self.value = value

    def __repr__(self):
        return "{}({})".format(self.__class__.__name__, self.value)

    def as_sql(self, compiler, connection):
        connection.ops.check_expression_support(self)
        val = self.value
        # check _output_field to avoid triggering an exception
        if self._output_field is not None:
            if self.for_save:
                val = self.output_field.get_db_prep_save(val, connection=connection)
            else:
                val = self.output_field.get_db_prep_value(val, connection=connection)
        if val is None:
            # cx_Oracle does not always convert None to the appropriate
            # NULL type (like in case expressions using numbers), so we
            # use a literal SQL NULL
            return 'NULL', []
        return '%s', [val]

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        c = super(Value, self).resolve_expression(query, allow_joins, reuse, summarize, for_save)
        c.for_save = for_save
        return c

    def get_group_by_cols(self):
        return []


class DurationValue(Value):
    def as_sql(self, compiler, connection):
        connection.ops.check_expression_support(self)
        if (connection.features.has_native_duration_field and
                connection.features.driver_supports_timedelta_args):
            return super(DurationValue, self).as_sql(compiler, connection)
        return connection.ops.date_interval_sql(self.value)


class RawSQL(Expression):
    contributes_to_group_by = True

    def __init__(self, sql, params, output_field=None):
        if output_field is None:
            output_field = fields.Field()
        self.sql, self.params = sql, params
        super(RawSQL, self).__init__(output_field=output_field)

    def __repr__(self):
        return "{}({}, {})".format(self.__class__.__name__, self.sql, self.params)

    def as_sql(self, compiler, connection):
        return '(%s)' % self.sql, self.params

    def get_group_by_cols(self):
        return [self]


class Star(Expression):
    def __repr__(self):
        return "'*'"

    def as_sql(self, compiler, connection):
        return '*', []


class Random(Expression):
    def __init__(self):
        super(Random, self).__init__(output_field=fields.FloatField())

    def __repr__(self):
        return "Random()"

    def as_sql(self, compiler, connection):
        return connection.ops.random_function_sql(), []


class Col(Expression):

    contains_column_references = True

    def __init__(self, alias, target, output_field=None):
        if output_field is None:
            output_field = target
        super(Col, self).__init__(output_field=output_field)
        self.alias, self.target = alias, target

    def __repr__(self):
        return "{}({}, {})".format(
            self.__class__.__name__, self.alias, self.target)

    def as_sql(self, compiler, connection):
        qn = compiler.quote_name_unless_alias
        return "%s.%s" % (qn(self.alias), qn(self.target.column)), []

    def relabeled_clone(self, relabels):
        return self.__class__(relabels.get(self.alias, self.alias), self.target, self.output_field)

    def get_group_by_cols(self):
        return [self]

    def get_db_converters(self, connection):
        if self.target == self.output_field:
            return self.output_field.get_db_converters(connection)
        return (self.output_field.get_db_converters(connection) +
                self.target.get_db_converters(connection))


class Ref(Expression):
    """
    Reference to column alias of the query. For example, Ref('sum_cost') in
    qs.annotate(sum_cost=Sum('cost')) query.
    """
    def __init__(self, refs, source):
        super(Ref, self).__init__()
        self.refs, self.source = refs, source

    def __repr__(self):
        return "{}({}, {})".format(self.__class__.__name__, self.refs, self.source)

    def get_source_expressions(self):
        return [self.source]

    def set_source_expressions(self, exprs):
        self.source, = exprs

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        # The sub-expression `source` has already been resolved, as this is
        # just a reference to the name of `source`.
        return self

    def relabeled_clone(self, relabels):
        return self

    def as_sql(self, compiler, connection):
        return "%s" % connection.ops.quote_name(self.refs), []

    def get_group_by_cols(self):
        return [self]


class ExpressionWrapper(Expression):
    """
    An expression that can wrap another expression so that it can provide
    extra context to the inner expression, such as the output_field.
    """

    def __init__(self, expression, output_field):
        super(ExpressionWrapper, self).__init__(output_field=output_field)
        self.expression = expression

    def set_source_expressions(self, exprs):
        self.expression = exprs[0]

    def get_source_expressions(self):
        return [self.expression]

    def as_sql(self, compiler, connection):
        return self.expression.as_sql(compiler, connection)

    def __repr__(self):
        return "{}({})".format(self.__class__.__name__, self.expression)


class When(Expression):
    template = 'WHEN %(condition)s THEN %(result)s'

    def __init__(self, condition=None, then=None, **lookups):
        if lookups and condition is None:
            condition, lookups = Q(**lookups), None
        if condition is None or not isinstance(condition, Q) or lookups:
            raise TypeError("__init__() takes either a Q object or lookups as keyword arguments")
        super(When, self).__init__(output_field=None)
        self.condition = condition
        self.result = self._parse_expressions(then)[0]

    def __str__(self):
        return "WHEN %r THEN %r" % (self.condition, self.result)

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self)

    def get_source_expressions(self):
        return [self.condition, self.result]

    def set_source_expressions(self, exprs):
        self.condition, self.result = exprs

    def get_source_fields(self):
        # We're only interested in the fields of the result expressions.
        return [self.result._output_field_or_none]

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        c = self.copy()
        c.is_summary = summarize
        if hasattr(c.condition, 'resolve_expression'):
            c.condition = c.condition.resolve_expression(query, allow_joins, reuse, summarize, False)
        c.result = c.result.resolve_expression(query, allow_joins, reuse, summarize, for_save)
        return c

    def as_sql(self, compiler, connection, template=None):
        connection.ops.check_expression_support(self)
        template_params = {}
        sql_params = []
        condition_sql, condition_params = compiler.compile(self.condition)
        template_params['condition'] = condition_sql
        sql_params.extend(condition_params)
        result_sql, result_params = compiler.compile(self.result)
        template_params['result'] = result_sql
        sql_params.extend(result_params)
        template = template or self.template
        return template % template_params, sql_params

    def get_group_by_cols(self):
        # This is not a complete expression and cannot be used in GROUP BY.
        cols = []
        for source in self.get_source_expressions():
            cols.extend(source.get_group_by_cols())
        return cols


class Case(Expression):
    """
    An SQL searched CASE expression:

        CASE
            WHEN n > 0
                THEN 'positive'
            WHEN n < 0
                THEN 'negative'
            ELSE 'zero'
        END
    """
    template = 'CASE %(cases)s ELSE %(default)s END'
    case_joiner = ' '

    def __init__(self, *cases, **extra):
        if not all(isinstance(case, When) for case in cases):
            raise TypeError("Positional arguments must all be When objects.")
        default = extra.pop('default', None)
        output_field = extra.pop('output_field', None)
        super(Case, self).__init__(output_field)
        self.cases = list(cases)
        self.default = self._parse_expressions(default)[0]

    def __str__(self):
        return "CASE %s, ELSE %r" % (', '.join(str(c) for c in self.cases), self.default)

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self)

    def get_source_expressions(self):
        return self.cases + [self.default]

    def set_source_expressions(self, exprs):
        self.cases = exprs[:-1]
        self.default = exprs[-1]

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        c = self.copy()
        c.is_summary = summarize
        for pos, case in enumerate(c.cases):
            c.cases[pos] = case.resolve_expression(query, allow_joins, reuse, summarize, for_save)
        c.default = c.default.resolve_expression(query, allow_joins, reuse, summarize, for_save)
        return c

    def copy(self):
        c = super(Case, self).copy()
        c.cases = c.cases[:]
        return c

    def as_sql(self, compiler, connection, template=None, extra=None):
        connection.ops.check_expression_support(self)
        if not self.cases:
            return compiler.compile(self.default)
        template_params = dict(extra) if extra else {}
        case_parts = []
        sql_params = []
        for case in self.cases:
            case_sql, case_params = compiler.compile(case)
            case_parts.append(case_sql)
            sql_params.extend(case_params)
        template_params['cases'] = self.case_joiner.join(case_parts)
        default_sql, default_params = compiler.compile(self.default)
        template_params['default'] = default_sql
        sql_params.extend(default_params)
        template = template or self.template
        sql = template % template_params
        if self._output_field_or_none is not None:
            sql = connection.ops.unification_cast_sql(self.output_field) % sql
        return sql, sql_params


class Date(Expression):
    """
    Add a date selection column.
    """
    def __init__(self, lookup, lookup_type):
        super(Date, self).__init__(output_field=fields.DateField())
        self.lookup = lookup
        self.col = None
        self.lookup_type = lookup_type

    def __repr__(self):
        return "{}({}, {})".format(self.__class__.__name__, self.lookup, self.lookup_type)

    def get_source_expressions(self):
        return [self.col]

    def set_source_expressions(self, exprs):
        self.col, = exprs

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        copy = self.copy()
        copy.col = query.resolve_ref(self.lookup, allow_joins, reuse, summarize)
        field = copy.col.output_field
        assert isinstance(field, fields.DateField), "%r isn't a DateField." % field.name
        if settings.USE_TZ:
            assert not isinstance(field, fields.DateTimeField), (
                "%r is a DateTimeField, not a DateField." % field.name
            )
        return copy

    def as_sql(self, compiler, connection):
        sql, params = self.col.as_sql(compiler, connection)
        assert not(params)
        return connection.ops.date_trunc_sql(self.lookup_type, sql), []

    def copy(self):
        copy = super(Date, self).copy()
        copy.lookup = self.lookup
        copy.lookup_type = self.lookup_type
        return copy

    def convert_value(self, value, expression, connection, context):
        if isinstance(value, datetime.datetime):
            value = value.date()
        return value


class DateTime(Expression):
    """
    Add a datetime selection column.
    """
    def __init__(self, lookup, lookup_type, tzinfo):
        super(DateTime, self).__init__(output_field=fields.DateTimeField())
        self.lookup = lookup
        self.col = None
        self.lookup_type = lookup_type
        if tzinfo is None:
            self.tzname = None
        else:
            self.tzname = timezone._get_timezone_name(tzinfo)
        self.tzinfo = tzinfo

    def __repr__(self):
        return "{}({}, {}, {})".format(
            self.__class__.__name__, self.lookup, self.lookup_type, self.tzinfo)

    def get_source_expressions(self):
        return [self.col]

    def set_source_expressions(self, exprs):
        self.col, = exprs

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        copy = self.copy()
        copy.col = query.resolve_ref(self.lookup, allow_joins, reuse, summarize)
        field = copy.col.output_field
        assert isinstance(field, fields.DateTimeField), (
            "%r isn't a DateTimeField." % field.name
        )
        return copy

    def as_sql(self, compiler, connection):
        sql, params = self.col.as_sql(compiler, connection)
        assert not(params)
        return connection.ops.datetime_trunc_sql(self.lookup_type, sql, self.tzname)

    def copy(self):
        copy = super(DateTime, self).copy()
        copy.lookup = self.lookup
        copy.lookup_type = self.lookup_type
        copy.tzname = self.tzname
        return copy

    def convert_value(self, value, expression, connection, context):
        if settings.USE_TZ:
            if value is None:
                raise ValueError(
                    "Database returned an invalid value in QuerySet.datetimes(). "
                    "Are time zone definitions for your database and pytz installed?"
                )
            value = value.replace(tzinfo=None)
            value = timezone.make_aware(value, self.tzinfo)
        return value


class OrderBy(BaseExpression):
    template = '%(expression)s %(ordering)s'

    def __init__(self, expression, descending=False):
        self.descending = descending
        if not hasattr(expression, 'resolve_expression'):
            raise ValueError('expression must be an expression type')
        self.expression = expression

    def __repr__(self):
        return "{}({}, descending={})".format(
            self.__class__.__name__, self.expression, self.descending)

    def set_source_expressions(self, exprs):
        self.expression = exprs[0]

    def get_source_expressions(self):
        return [self.expression]

    def as_sql(self, compiler, connection):
        connection.ops.check_expression_support(self)
        expression_sql, params = compiler.compile(self.expression)
        placeholders = {
            'expression': expression_sql,
            'ordering': 'DESC' if self.descending else 'ASC',
        }
        return (self.template % placeholders).rstrip(), params

    def get_group_by_cols(self):
        cols = []
        for source in self.get_source_expressions():
            cols.extend(source.get_group_by_cols())
        return cols

    def reverse_ordering(self):
        self.descending = not self.descending
        return self

    def asc(self):
        self.descending = False

    def desc(self):
        self.descending = True
