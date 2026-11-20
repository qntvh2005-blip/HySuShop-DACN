from django.core.paginator import Paginator


def page_context(request, queryset, *, size=24, fields=None):
    """Build a page and retain its filters without repeating the page parameter."""
    query = request.GET.copy()
    query.pop("page", None)
    if fields is not None:
        for key in list(query):
            if key not in fields:
                query.pop(key)
    return {
        "page_obj": Paginator(queryset, size).get_page(request.GET.get("page")),
        "query_string": query.urlencode(),
    }
