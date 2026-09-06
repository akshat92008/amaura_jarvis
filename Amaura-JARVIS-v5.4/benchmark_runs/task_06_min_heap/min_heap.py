class MinHeap:
    def __init__(self):
        self.heap = []

    def push(self, val: int) -> None:
        """Add an element to the heap while maintaining the heap property."""
        self.heap.append(val)
        self._bubble_up(len(self.heap) - 1)

    def pop(self) -> int:
        """Remove and return the smallest element from the heap."""
        if not self.heap:
            raise IndexError("pop from empty heap")

        # Swap root with last element
        self._swap(0, len(self.heap) - 1)
        min_val = self.heap.pop()
        self._bubble_down(0)
        return min_val

    def peek(self) -> int:
        """Return the smallest element without removing it."""
        if not self.heap:
            raise IndexError("peek from empty heap")
        return self.heap[0]

    def __len__(self) -> int:
        """Return the number of elements in the heap."""
        return len(self.heap)

    def _bubble_up(self, index: int) -> None:
        """Move the element at the given index up to maintain heap property."""
        parent = (index - 1) // 2
        if index > 0 and self.heap[index] < self.heap[parent]:
            self._swap(index, parent)
            self._bubble_up(parent)

    def _bubble_down(self, index: int) -> None:
        """Move the element at the given index down to maintain heap property."""
        left = 2 * index + 1
        right = 2 * index + 2
        smallest = index

        if left < len(self.heap) and self.heap[left] < self.heap[smallest]:
            smallest = left
        if right < len(self.heap) and self.heap[right] < self.heap[smallest]:
            smallest = right

        if smallest != index:
            self._swap(index, smallest)
            self._bubble_down(smallest)

    def _swap(self, i: int, j: int) -> None:
        """Swap elements at indices i and j."""
        self.heap[i], self.heap[j] = self.heap[j], self.heap[i]
