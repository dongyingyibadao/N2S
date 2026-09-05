class QuantizedPolicy:
    def infer(self, images):
        prefix_embs, prefix_pad_masks, prefix_att_masks = self.embed_prefix(images)
        return self.quantized_attention(prefix_embs)
