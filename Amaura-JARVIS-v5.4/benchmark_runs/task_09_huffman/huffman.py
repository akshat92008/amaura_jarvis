import heapq
from collections import defaultdict

class HuffmanCoding:
    def __init__(self):
        self.heap = []
        self.codes = {}

    class HeapNode:
        def __init__(self, char, freq):
            self.char = char
            self.freq = freq
            self.left = None
            self.right = None

        def __lt__(self, other):
            return self.freq < other.freq

    def make_frequency_dict(self, text):
        frequency = defaultdict(int)
        for char in text:
            frequency[char] += 1
        return frequency

    def make_heap(self, frequency):
        for key in frequency:
            node = self.HeapNode(key, frequency[key])
            heapq.heappush(self.heap, node)

    def merge_nodes(self):
        while len(self.heap) > 1:
            node1 = heapq.heappop(self.heap)
            node2 = heapq.heappop(self.heap)

            merged = self.HeapNode(None, node1.freq + node2.freq)
            merged.left = node1
            merged.right = node2

            heapq.heappush(self.heap, merged)

    def make_codes_helper(self, root, current_code):
        if root is None:
            return

        if root.char is not None:
            self.codes[root.char] = current_code
            return

        self.make_codes_helper(root.left, current_code + "0")
        self.make_codes_helper(root.right, current_code + "1")

    def make_codes(self):
        root = heapq.heappop(self.heap)
        current_code = ""
        self.make_codes_helper(root, current_code)

    def get_encoded_text(self, text):
        encoded_text = ""
        for char in text:
            encoded_text += self.codes[char]
        return encoded_text

    def pad_encoded_text(self, encoded_text):
        extra_padding = 8 - len(encoded_text) % 8
        for i in range(extra_padding):
            encoded_text += "0"

        padded_info = "{0:08b}".format(extra_padding)
        encoded_text = padded_info + encoded_text
        return encoded_text

    def encode(self, text: str) -> tuple[str, Any]:
        frequency = self.make_frequency_dict(text)
        self.make_heap(frequency)
        self.merge_nodes()
        self.make_codes()

        encoded_text = self.get_encoded_text(text)
        padded_encoded_text = self.pad_encoded_text(encoded_text)

        return padded_encoded_text, self.heap[0]

    def decode(self, encoded_bits: str, tree: Any) -> str:
        current_code = ""
        decoded_text = ""

        for bit in encoded_bits:
            current_code += bit
            if current_code in self.codes.values():
                for char, code in self.codes.items():
                    if code == current_code:
                        decoded_text += char
                        current_code = ""
                        break

        return decoded_text

# Example usage:
if __name__ == "__main__":
    huffman = HuffmanCoding()
    text = "this is an example for huffman encoding"
    encoded_text, tree = huffman.encode(text)
    print(f"Encoded text: {encoded_text}")
    decoded_text = huffman.decode(encoded_text, tree)
    print(f"Decoded text: {decoded_text}")
