from django.core import checks
from django.db.models import Field, FloatField
from django.db.models.expressions import CombinedExpression, Func, Value
from django.db.models.functions import Coalesce
from django.db.models.lookups import Lookup
from django.utils.translation import ugettext_lazy as _


class SearchVectorExact(Lookup):
    lookup_name = 'exact'

    def process_rhs(self, qn, connection):
        if not hasattr(self.rhs, 'resolve_expression'):
            config = getattr(self.lhs, 'config', None)
            self.rhs = SearchQuery(self.rhs, config=config)
        rhs, rhs_params = super(SearchVectorExact, self).process_rhs(qn, connection)
        return rhs, rhs_params

    def as_sql(self, qn, connection):
        lhs, lhs_params = self.process_lhs(qn, connection)
        rhs, rhs_params = self.process_rhs(qn, connection)
        params = lhs_params + rhs_params
        return '%s @@ %s = true' % (lhs, rhs), params


class WeightedColumn:

    def __init__(self, name, weight):
        assert isinstance(name, str)
        assert weight in ('A', 'B', 'C', 'D')
        self.name = name
        self.weight = weight

    def deconstruct(self):
        path = "%s.%s" % (self.__class__.__module__, self.__class__.__name__)
        return path, [self.name, self.weight], {}


class SearchVectorField(Field):
    description = _("PostgreSQL tsvector field.")

    def __init__(self, columns=None, language=None, *args, **kwargs):
        self.columns = columns
        self.language = language
        kwargs['db_index'] = True
        kwargs['null'] = True
        super(SearchVectorField, self).__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super(SearchVectorField, self).deconstruct()
        if self.columns is not None:
            kwargs['columns'] = self.columns
        if self.language is not None:
            kwargs['language'] = self.language
        del kwargs['db_index']
        del kwargs['null']
        return name, path, args, kwargs

    def check(self, **kwargs):
        errors = super(SearchVectorField, self).check(**kwargs)
        if self.columns is not None:
            errors.extend(self._check_columns_attribute(**kwargs))
            errors.extend(self._check_language_attribute(**kwargs))
        return errors

    def _check_columns_attribute(self, **kwargs):
        if not isinstance(self.columns, (list, tuple)) or \
                not all(isinstance(tsv, WeightedColumn) for tsv in self.columns):
            return [
                checks.Error(
                    "'columns' must be a list or tuple of WeightedColumn instances.",
                    obj=self,
                    id='fields.E402',
                )
            ]
        else:
            return []

    def _check_language_attribute(self, **kwargs):
        if self.language is None:
            return [
                checks.Error(
                    "{} must define a 'language' attribute.".format(self.__class__.__name__),
                    obj=self,
                    id='fields.E403',
                )
            ]
        elif not isinstance(self.language, str):
            return [
                checks.Error(
                    "'language' must be a string.",
                    obj=self,
                    id='fields.E404',
                )
            ]
        else:
            return []

    def db_type(self, connection):
        return 'tsvector'


class SearchQueryField(Field):

    def db_type(self, connection):
        return 'tsquery'


class SearchVectorCombinable(object):
    ADD = '||'

    def _combine(self, other, connector, reversed, node=None):
        if not isinstance(other, SearchVectorCombinable) or not self.config == other.config:
            raise TypeError('SearchVector can only be combined with other SearchVectors')
        if reversed:
            return CombinedSearchVector(other, connector, self, self.config)
        return CombinedSearchVector(self, connector, other, self.config)


class SearchVector(SearchVectorCombinable, Func):
    function = 'to_tsvector'
    arg_joiner = " || ' ' || "
    _output_field = SearchVectorField()
    config = None

    def __init__(self, *expressions, **extra):
        super(SearchVector, self).__init__(*expressions, **extra)
        self.source_expressions = [
            Coalesce(expression, Value('')) for expression in self.source_expressions
        ]
        self.config = self.extra.get('config', self.config)
        weight = self.extra.get('weight')
        if weight is not None and not hasattr(weight, 'resolve_expression'):
            weight = Value(weight)
        self.weight = weight

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        resolved = super(SearchVector, self).resolve_expression(query, allow_joins, reuse, summarize, for_save)
        if self.config:
            if not hasattr(self.config, 'resolve_expression'):
                resolved.config = Value(self.config).resolve_expression(query, allow_joins, reuse, summarize, for_save)
            else:
                resolved.config = self.config.resolve_expression(query, allow_joins, reuse, summarize, for_save)
        return resolved

    def as_sql(self, compiler, connection, function=None, template=None):
        config_params = []
        if template is None:
            if self.config:
                config_sql, config_params = compiler.compile(self.config)
                template = "%(function)s({}::regconfig, %(expressions)s)".format(config_sql.replace('%', '%%'))
            else:
                template = self.template
        sql, params = super(SearchVector, self).as_sql(compiler, connection, function=function, template=template)
        extra_params = []
        if self.weight:
            weight_sql, extra_params = compiler.compile(self.weight)
            sql = 'setweight({}, {})'.format(sql, weight_sql)
        return sql, config_params + params + extra_params


class CombinedSearchVector(SearchVectorCombinable, CombinedExpression):
    def __init__(self, lhs, connector, rhs, config, output_field=None):
        self.config = config
        super(CombinedSearchVector, self).__init__(lhs, connector, rhs, output_field)


class SearchQueryCombinable(object):
    BITAND = '&&'
    BITOR = '||'

    def _combine(self, other, connector, reversed, node=None):
        if not isinstance(other, SearchQueryCombinable):
            raise TypeError(
                'SearchQuery can only be combined with other SearchQuerys, '
                'got {}.'.format(type(other))
            )
        if not self.config == other.config:
            raise TypeError("SearchQuery configs don't match.")
        if reversed:
            return CombinedSearchQuery(other, connector, self, self.config)
        return CombinedSearchQuery(self, connector, other, self.config)

    # On Combinable, these are not implemented to reduce confusion with Q. In
    # this case we are actually (ab)using them to do logical combination so
    # it's consistent with other usage in Django.
    def __or__(self, other):
        return self._combine(other, self.BITOR, False)

    def __ror__(self, other):
        return self._combine(other, self.BITOR, True)

    def __and__(self, other):
        return self._combine(other, self.BITAND, False)

    def __rand__(self, other):
        return self._combine(other, self.BITAND, True)


class SearchQuery(SearchQueryCombinable, Value):
    invert = False
    _output_field = SearchQueryField()
    config = None

    def __init__(self, value, output_field=None, **extra):
        self.config = extra.pop('config', self.config)
        self.invert = extra.pop('invert', self.invert)
        super(SearchQuery, self).__init__(value, output_field=output_field)

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        resolved = super(SearchQuery, self).resolve_expression(query, allow_joins, reuse, summarize, for_save)
        if self.config:
            if not hasattr(self.config, 'resolve_expression'):
                resolved.config = Value(self.config).resolve_expression(query, allow_joins, reuse, summarize, for_save)
            else:
                resolved.config = self.config.resolve_expression(query, allow_joins, reuse, summarize, for_save)
        return resolved

    def as_sql(self, compiler, connection):
        params = [self.value]
        if self.config:
            config_sql, config_params = compiler.compile(self.config)
            template = 'plainto_tsquery({}::regconfig, %s)'.format(config_sql)
            params = config_params + [self.value]
        else:
            template = 'plainto_tsquery(%s)'
        if self.invert:
            template = '!!({})'.format(template)
        return template, params

    def _combine(self, other, connector, reversed, node=None):
        combined = super(SearchQuery, self)._combine(other, connector, reversed, node)
        combined.output_field = SearchQueryField()
        return combined

    def __invert__(self):
        extra = {
            'invert': not self.invert,
            'config': self.config,
        }
        return type(self)(self.value, **extra)


class CombinedSearchQuery(SearchQueryCombinable, CombinedExpression):
    def __init__(self, lhs, connector, rhs, config, output_field=None):
        self.config = config
        super(CombinedSearchQuery, self).__init__(lhs, connector, rhs, output_field)


class SearchRank(Func):
    function = 'ts_rank'
    _output_field = FloatField()

    def __init__(self, vector, query, **extra):
        if not hasattr(vector, 'resolve_expression'):
            vector = SearchVector(vector)
        if not hasattr(query, 'resolve_expression'):
            query = SearchQuery(query)
        weights = extra.get('weights')
        if weights is not None and not hasattr(weights, 'resolve_expression'):
            weights = Value(weights)
        self.weights = weights
        super(SearchRank, self).__init__(vector, query, **extra)

    def as_sql(self, compiler, connection, function=None, template=None):
        extra_params = []
        extra_context = {}
        if template is None and self.extra.get('weights'):
            if self.weights:
                template = '%(function)s(%(weights)s, %(expressions)s)'
                weight_sql, extra_params = compiler.compile(self.weights)
                extra_context['weights'] = weight_sql
        sql, params = super(SearchRank, self).as_sql(
            compiler, connection,
            function=function, template=template, **extra_context
        )
        return sql, extra_params + params


SearchVectorField.register_lookup(SearchVectorExact)


class TrigramBase(Func):
    def __init__(self, expression, string, **extra):
        if not hasattr(string, 'resolve_expression'):
            string = Value(string)
        super(TrigramBase, self).__init__(expression, string, output_field=FloatField(), **extra)


class TrigramSimilarity(TrigramBase):
    function = 'SIMILARITY'


class TrigramDistance(TrigramBase):
    function = ''
    arg_joiner = ' <-> '
