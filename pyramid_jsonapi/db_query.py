from pyramid.httpexceptions import HTTPBadRequest
from pyramid_jsonapi.http_query import QueryInfo
from rqlalchemy import RQLQueryMixIn
from sqlalchemy.orm import load_only, Query as BaseQuery


class PJQueryMixin:

    @staticmethod
    def from_view(view, **kwargs):
        query = view.dbsession.query(
            view.model
        )
        query.__class__ = RQLQuery
        query.pj_view = view
        return query.pj_options(**kwargs)

    def pj_options(self, **kwargs):
        query = self
        for key, val in kwargs.items():
            query = getattr(query, f'_opt_{key}')(val)
        return query

    def _opt_loadonly(self, loadonly):
        if not loadonly:
            loadonly = self.pj_view.allowed_requested_query_columns.keys()
        return self.options(load_only(*loadonly))

    def pj_count(self):
        return self.count()

    def add_filtering(self):
        return self.pj_view.query_add_filtering(self)

    def add_relative_paging(self):
        query = self
        view = self.pj_view
        qinfo = QueryInfo(view.__class__, view.request)
        pinfo = qinfo.paging_info

        # We just add filters here. The necessary joins will have been done by the
        # Sorting that after relies on.
        # Need >= or <= on all but the last prop.
        if pinfo.start_type.endswith('_id'):
            before_after = self.before_after_from_id(qinfo, pinfo.item_id)
        else:
            before_after = pinfo.before_after
        for sinfo, after in zip(qinfo.sorting_info[:-1], before_after[:-1]):
            ascending = not sinfo.ascending if query._pj_reversed else sinfo.ascending
            if ascending:
                query = query.filter(sinfo.prop >= after)
            else:
                query = query.filter(sinfo.prop <= after)
        # And > or < on the last one.
        ascending = qinfo.sorting_info[-1].ascending
        ascending = not ascending if query._pj_reversed else ascending
        # first and last have empty before_afters
        if before_after:
            if ascending:
                query = query.filter(qinfo.sorting_info[-1].prop > before_after[-1])
            else:
                query = query.filter(qinfo.sorting_info[-1].prop < before_after[-1])

        return query

    def before_after_from_id(self, qinfo, item_id):
        item = self.pj_view.get_item(item_id)
        if not item:
            raise HTTPBadRequest(f'Could not find item with after_id {item_id}')
        vals = [self.get_prop_value(item, info) for info in qinfo.sorting_info]
        return vals

    def get_prop_value(self, item, prop_info):
        val = item
        for key in prop_info.colspec:
            val = getattr(val, key)
        return val

    def id_only(self):
        return self.options(load_only(self.pj_view.key_column.name))

    def iterate_paged(self, page_size=None):
        page_size = page_size or self.pj_view.query_info.paging_info.limit
        cur_query = self.limit(page_size)
        records_yielded = 0
        records_from_cur = 0
        while True:
            # Loop through records in a page:
            for record in cur_query:
                records_yielded += 1
                records_from_cur += 1
                yield record
            # End of a page
            if records_from_cur < page_size:
                break
            records_from_cur = 0
            cur_query = self.offset(records_yielded).limit(page_size)


class RQLQuery(BaseQuery, RQLQueryMixIn, PJQueryMixin):

    def _rql_ilike(self, args):
        attr, value = args

        attr = self._rql_attr(attr)
        value = self._rql_value(value, attr)
        value = value.replace("*", "%")

        return attr.ilike(value)

    def _rql_icontains(self, args):
        attr, value = args
        attr = self._rql_attr(attr)
        value = self._rql_value(value, attr)
        return attr.ilike(f'%{value}%')

    def _rql_isempty(self, args):
        attr = self._rql_attr(args[0])
        return attr.__eq__('')

    def _rql_isnull(self, args):
        attr = self._rql_attr(args[0])
        # None value translates to 'IS NULL'
        return attr.__eq__(None)

    def _rql_isnotempty(self, args):
        attr = self._rql_attr(args[0])
        return attr.__ne__('')

    def _rql_isnotnull(self, args):
        attr = self._rql_attr(args[0])
        # None value translates to 'IS NOT NULL'
        return attr.__ne__(None)

    def _rql_istrue(self, args):
        attr = self._rql_attr(args[0])
        return attr.__eq__(True)

    def _rql_isfalse(self, args):
        attr = self._rql_attr(args[0])
        return attr.__eq__(False)
