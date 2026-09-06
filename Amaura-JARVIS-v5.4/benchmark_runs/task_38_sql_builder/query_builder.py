class QueryBuilder:
    def __init__(self):
        self._table = None
        self._select = []
        self._where = None
        self._limit = None

    def table(self, name: str) -> 'QueryBuilder':
        self._table = name
        return self

    def select(self, *cols: str) -> 'QueryBuilder':
        self._select.extend(cols)
        return self

    def where(self, condition: str) -> 'QueryBuilder':
        self._where = condition
        return self

    def limit(self, n: int) -> 'QueryBuilder':
        self._limit = n
        return self

    def build(self) -> str:
        if not self._table:
            raise ValueError("Table name must be specified")
        if not self._select:
            raise ValueError("At least one column must be selected")

        query = f"SELECT {', '.join(self._select)} FROM {self._table}"
        if self._where:
            query += f" WHERE {self._where}"
        if self._limit:
            query += f" LIMIT {self._limit}"
        return query

# Example usage:
# query = QueryBuilder().table("users").select("id", "name").where("age > 18").limit(10).build()
# print(query)  # SELECT id, name FROM users WHERE age > 18 LIMIT 10