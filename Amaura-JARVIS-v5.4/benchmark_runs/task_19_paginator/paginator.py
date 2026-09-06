class Paginator:
    def __init__(self, items: list, page_size: int):
        self.items = items
        self.page_size = page_size
        self.total_pages = (len(items) + page_size - 1) // page_size

    def get_page(self, page_num: int) -> dict:
        if page_num < 1 or page_num > self.total_pages:
            raise ValueError("Invalid page number")

        start_index = (page_num - 1) * self.page_size
        end_index = start_index + self.page_size
        page_items = self.items[start_index:end_index]

        return {
            'items': page_items,
            'page': page_num,
            'total_pages': self.total_pages,
            'has_next': page_num < self.total_pages,
            'has_prev': page_num > 1
        }