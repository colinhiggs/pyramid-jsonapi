from sqlalchemy.orm import load_only, Query as BaseQuery
from rqlalchemy import RQLQueryMixIn

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
