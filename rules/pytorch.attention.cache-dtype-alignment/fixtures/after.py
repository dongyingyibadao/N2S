class Policy:
    def train_forward(self, actions):
        target_dtype = self.backbone.language_model.layers[0].self_attn.q_proj.weight.dtype
        return actions.to(dtype=target_dtype)

    def infer(self, images, masks, tokens):
        prefix_embs, prefix_pad_masks, prefix_att_masks = self.embed_prefix(images, masks, tokens)
        prefix_dtype = self.backbone.language_model.layers[0].self_attn.q_proj.weight.dtype
        prefix_embs = prefix_embs.to(dtype=prefix_dtype)
        return self.backbone(inputs_embeds=[prefix_embs, None], use_cache=True)
