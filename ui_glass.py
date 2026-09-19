# -*- coding: utf-8 -*-
"""自定义背景 + 半透明「玻璃」界面。

CustomTkinter 没有真透明：每个控件都会用一层纯色盖住自己的区域，
fg_color="transparent" 也只是「填父容器的颜色」。所以这里的做法是
把背景图按位置切片贴进每个控件内部（详见 _glass_walk / _glass_paint）。

这些方法都是 MainApp 的一部分（通过 GlassMixin 混入），直接用 self。"""
from pathlib import Path

import tkinter as tk

from ui_base import (
    BG,
)


class GlassMixin:
    # 图形直接画在自己画布上的控件：贴图会盖住图形（开关的轨道、滑块的槽），
    # 改成把图垫在画布最底层（图片在图形下面、画布底色上面）。
    # 滚动条不在里面 —— 它的滑块是个独立控件（在画布上面），
    # 所以滚动条的底槽可以直接透明掉。
    _GLASS_ON_CANVAS = ("CTkSwitch", "CTkSlider")
    # 圆角遮罩缓存（避免每次都重新画）
    _MASK_CACHE = {}

    def _on_resize(self, event=None):
        """窗口尺寸变化时（去抖）重新生成背景，避免频繁重绘"""
        # <Configure> 绑在窗口上时，子控件的尺寸变化也会冒泡到这里，
        # 只处理窗口本身的变化（否则一切换页面就重算一遍背景，很卡）
        if event is not None and getattr(event, "widget", None) is not self:
            return
        if getattr(self, "_resize_after", None):
            try:
                self.after_cancel(self._resize_after)
            except Exception:
                pass
        self._resize_after = self.after(150, self._apply_background)

    @staticmethod
    def _as_hex(color):
        """把控件颜色统一成 '#RRGGBB'；transparent / None 返回 None"""
        if isinstance(color, (list, tuple)):
            color = color[-1] if color else None
        if not isinstance(color, str):
            return None
        if color.lower() == "transparent":
            return None
        if len(color) == 7 and color.startswith("#"):
            return color.upper()
        try:
            from PIL import ImageColor
            r, g, b = ImageColor.getrgb(color)[:3]
            return "#%02X%02X%02X" % (r, g, b)
        except Exception:
            return None

    @staticmethod
    def _rgb(hexcolor):
        h = hexcolor.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    def _w_fg(self, w):
        try:
            return self._as_hex(w.cget("fg_color"))
        except Exception:
            return None

    def _glass_alpha(self):
        """面板透明度：0=全透明，1=完全不透明"""
        try:
            return max(0.0, min(1.0, float(self.settings.get("panel_opacity", 0.5))))
        except Exception:
            return 0.5

    def _glass_base(self, tint, alpha, blur=False):
        """整窗玻璃底图 = 背景图按 alpha 混上控件颜色（带缓存）

        缓存键必须带上 alpha —— 结构层是 0（纯原图），面板层是面板透明度，
        两者交替调用；键里少了 alpha 就会每次都重建，慢十几倍。
        """
        cache = getattr(self, "_glass_cache", None)
        _a = round(alpha, 3)
        if cache is None:
            cache = {}
            self._glass_cache = cache
        # 换透明度时，把上一批别的 alpha 的整窗图丢掉，避免占内存
        allow = getattr(self, "_glass_cache_alphas", None)
        if allow is None:
            allow = {_a}
            self._glass_cache_alphas = allow
        elif _a not in allow:
            allow.add(_a)
            for k in [k for k in cache if k[2] not in allow]:
                cache.pop(k, None)
        key = (tint, bool(blur), _a)
        hit = cache.get(key)
        if hit is not None:
            return hit
        from PIL import Image
        base = self._bg_img
        if blur:
            from PIL import ImageFilter
            base = base.filter(ImageFilter.GaussianBlur(10))
            base = Image.blend(base, Image.new("RGB", base.size, (12, 12, 14)), 0.35)
        if _a <= 0.001:
            out = base
        else:
            out = Image.blend(base, Image.new("RGB", base.size, self._rgb(tint)), _a)
        cache[key] = out
        return out

    def _glass_schedule_refresh(self, delay=25):
        """「刚有控件显示出来」时补贴一次玻璃。

        什么时候需要：展开明细、下拉浮层弹出来 —— 这些控件之前是不可见的，
        我们的遍历会跳过不可见控件，所以它们身上没有玻璃，会露出自己的实色底。
        这里延后一点点整体补一次（贴过的会跳过，所以不算慢）。
        """
        if not self.settings.get("bg_image"):
            return
        try:
            if getattr(self, "_glass_refresh_after", None):
                try:
                    self.after_cancel(self._glass_refresh_after)
                except Exception:
                    pass
            self._glass_refresh_after = self.after(delay, self._glass_refresh_now)
        except Exception:
            pass

    def _glass_refresh_now(self):
        self._glass_refresh_after = None
        try:
            self._apply_background()
        except Exception:
            pass

    def _glass_clear(self):
        """清掉所有玻璃层，并把改过的文字底色还原"""
        for w, info in list(getattr(self, "_glass_placed", {}).items()):
            lbl = info.get("lbl")
            if lbl is not None:
                try:
                    lbl.destroy()
                except Exception:
                    pass
            try:
                if info.get("kind") in ("item", "under", "viewport"):
                    w.delete("glassbg")
                cv = getattr(w, "_canvas", None)
                if cv is not None and cv.winfo_exists():
                    cv.delete("glassbg")
            except Exception:
                pass
        self._glass_placed = {}
        for t, orig in list(getattr(self, "_glass_text_orig", {}).items()):
            try:
                if t.winfo_exists():
                    bg, img, comp = orig[:3]
                    t.configure(bg=bg, image=(img if img else ""),
                                compound=(comp or "none"))
            except Exception:
                pass
        self._glass_text_orig = {}
        self._glass_text_photos = {}
        self._glass_text_last = {}
        self._glass_text_size = {}
        for t, vals in list(getattr(self, "_glass_color_orig", {}).items()):
            try:
                if t.winfo_exists():
                    t.configure(**vals)
            except Exception:
                pass
        self._glass_color_orig = {}
        for lbl in getattr(self, "_bg_layers", []):
            try:
                lbl.destroy()
            except Exception:
                pass
        self._bg_layers = []
        self._bg_photos = []

    def _glass_rect(self, w):
        return (w.winfo_rootx() - self.winfo_rootx(),
                w.winfo_rooty() - self.winfo_rooty(),
                w.winfo_width(), w.winfo_height())

    @staticmethod
    def _glass_crop(base, rect):
        """从整图里裁出 rect 位置的那一块（越界部分填黑）"""
        from PIL import Image
        ox, oy, cw, ch = rect
        if cw < 2 or ch < 2:
            return None
        crop = Image.new("RGB", (cw, ch), (0, 0, 0))
        sx, sy = max(0, ox), max(0, oy)
        ex, ey = min(base.width, ox + cw), min(base.height, oy + ch)
        if ex > sx and ey > sy:
            crop.paste(base.crop((sx, sy, ex, ey)), (sx - ox, sy - oy))
        return crop

    @staticmethod
    def _rounded_mask(size, radius):
        """圆角矩形遮罩（用来把卡片切成圆角）"""
        w, h = int(size[0]), int(size[1])
        radius = max(0, min(int(radius), min(w, h) // 2))
        key = (w, h, radius)
        cache = GlassMixin._MASK_CACHE
        hit = cache.get(key)
        if hit is not None:
            return hit
        from PIL import Image, ImageDraw
        m = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(m)
        if radius <= 0:
            d.rectangle([0, 0, w - 1, h - 1], fill=255)
        else:
            d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
        if len(cache) > 300:
            cache.clear()
        cache[key] = m
        return m

    def _glass_fix_text(self, w, base):
        """控件内部的文字标签自带一块不透明底色。

        tk 的标签不能真透明，但可以「图片 + 文字」一起显示：
        把该位置的真实玻璃图铺满标签、文字叠在上面，底色就彻底看不出来了。
        （只把底色改成一块平均色的话，在有花纹的背景图上还是能看出方块。）
        输入框内部的 tk.Entry 不支持图片，只能给它一块平均色。

        关键：图要按【去掉内边距 / 边框之后的内尺寸】裁。
        tk 标签的请求宽度 = max(文字宽, 图片宽) + 2*padx + 2*border，
        直接按整个标签的尺寸裁图的话，请求宽度每贴一次就涨一点，
        会无限膨胀（之前右上角叉号一直变大就是这个原因）；
        按内尺寸裁尺寸就不变，也就不需要去动标签的内边距了。
        —— 早先的写法是「把内边距清零，然后跳过这一轮、等下一次
        <Configure> 再回来贴图」，但那次 Configure 经常不来
        （按钮的字标签 borderwidth=1，就会踩到这条路），
        结果文字一直带着自己的实色底。现在一次贴好，不依赖第二轮。
        """
        from PIL import Image, ImageTk
        for attr in ("_label", "_text_label", "_entry"):
            t = getattr(w, attr, None)
            if t is None:
                continue
            try:
                if not t.winfo_exists() or not t.winfo_ismapped():
                    continue
                rect = self._glass_rect(t)
                if rect[2] < 2 or rect[3] < 2:
                    continue
                # 尺寸和底图都没变、图也已经贴过，就不用重做（悬停时会频繁重画）
                last = getattr(self, "_glass_text_last", None)
                if last is None:
                    last = {}
                    self._glass_text_last = last
                if last.get(t) == (rect, id(base)) and t.cget("image"):
                    continue
                # 防止万一还是变大：标签一旦比我们贴过的尺寸还大，就不再贴
                sizes = getattr(self, "_glass_text_size", None)
                if sizes is None:
                    sizes = {}
                    self._glass_text_size = sizes
                prev = sizes.get(t)
                if prev is not None and (rect[2] > prev[0] + 6 or rect[3] > prev[1] + 6):
                    continue

                from PIL import Image
                if t not in self._glass_text_orig:
                    self._glass_text_orig[t] = (t.cget("bg"), t.cget("image"),
                                                t.cget("compound"))

                # 去掉内边距 / 边框之后的内尺寸（裁图用这个尺寸，标签才不会变大）
                try:
                    bx = int(t.cget("borderwidth")) + int(t.cget("highlightthickness"))
                    pad_x = 2 * (int(t.cget("padx")) + bx)
                    pad_y = 2 * (int(t.cget("pady")) + bx)
                except Exception:
                    pad_x = pad_y = 0
                inner = (rect[0] + pad_x // 2, rect[1] + pad_y // 2,
                         max(2, rect[2] - pad_x), max(2, rect[3] - pad_y))

                crop = self._glass_crop(base, inner)
                if crop is None:
                    continue
                r, g, b = crop.resize((1, 1), Image.BILINEAR).getpixel((0, 0))
                avg = "#%02X%02X%02X" % (r, g, b)
                if attr == "_entry":
                    if str(t.cget("bg")) != avg:
                        t.configure(bg=avg)
                    last[t] = (rect, id(base))
                    continue
                photo = ImageTk.PhotoImage(crop)
                if not hasattr(self, "_glass_text_photos"):
                    self._glass_text_photos = {}
                self._glass_text_photos[t] = photo      # 保住引用，否则图会被回收
                # 只在真的不一样时才设（无条件 configure 会反复触发重绘）
                try:
                    if str(t.cget("bg")) == avg and t.cget("compound") == "center" \
                            and str(t.cget("image")) == str(photo):
                        last[t] = (rect, id(base))
                        continue
                except Exception:
                    pass
                t.configure(bg=avg, image=photo, compound="center")
                sizes[t] = (rect[2], rect[3])
                last[t] = (rect, id(base))
            except Exception:
                pass

    def _glass_compose(self, w, tint, alpha, blur, pbase, rect):
        """裁出该控件的玻璃切片；有圆角的话把圆角外面的部分换成「底下的那层玻璃」

        这样卡片就是圆角的，而不是一块盖住圆角的直角矩形。
        """
        own = self._glass_crop(self._glass_base(tint, alpha, blur), rect)
        if own is None:
            return None
        radius = 0
        try:
            radius = int(w.cget("corner_radius"))
        except Exception:
            radius = 0
        if radius <= 0:
            return own
        under = self._glass_crop(pbase if pbase is not None else self._bg_img, rect)
        if under is None:
            return own
        out = under.copy()
        out.paste(own, (0, 0), self._rounded_mask((rect[2], rect[3]), radius))
        return out

    def _glass_raise(self, w):
        """把玻璃图抬到控件自己的底色之上（边框、文字、图标仍在它上面）"""
        try:
            cv = getattr(w, "_canvas", None)
            if cv is None or not cv.winfo_exists():
                return
            if cv.find_withtag("inner_parts"):
                cv.tag_raise("glassbg", "inner_parts")
            else:
                cv.tag_raise("glassbg")
        except Exception:
            pass

    def _glass_hook_draw(self, w):
        """控件重画（悬停变色、改文字…）之后，把玻璃图重新抬上来"""
        if getattr(w, "_glass_draw_hooked", False):
            return
        orig = getattr(w, "_draw", None)
        if orig is None or not callable(orig):
            return

        def patched(*a, **kw):
            r = orig(*a, **kw)
            try:
                self._glass_raise(w)
                info = self._glass_placed.get(w)
                if info is not None and info["lbl"] is None:
                    self._glass_fix_text(
                        w, self._glass_base(info["tint"], info["alpha"], info.get("blur", False)))
            except Exception:
                pass
            return r

        try:
            w._draw = patched
            w._glass_draw_hooked = True
        except Exception:
            pass

    def _glass_paint(self, w, tint, alpha, blur=False, pbase=None):
        """给控件贴一块玻璃（盖住它自己的底色，但在它的文字/图标下面）

        优先画在控件自己的画布上（画布上的一项）—— 这样不会多出一层窗口，
        鼠标点击不会被挡住（以前用子窗口贴图，必须点到字上才管用）。
        """
        from PIL import ImageTk
        try:
            if not w.winfo_exists() or not w.winfo_ismapped():
                return
        except Exception:
            return
        rect = self._glass_rect(w)
        if rect[2] < 2 or rect[3] < 2:
            return
        canvas = getattr(w, "_canvas", None)
        use_item = canvas is not None
        try:
            if use_item and not canvas.winfo_exists():
                use_item = False
        except Exception:
            use_item = False

        key = ("L", tint, round(alpha, 3), bool(blur), rect, use_item)
        placed = getattr(self, "_glass_placed", None)
        if placed is None:
            placed = {}
            self._glass_placed = placed
        old = placed.get(w)
        if old is not None and old["key"] == key:
            if use_item:
                self._glass_raise(w)
                return
            try:
                if old["lbl"] is not None and old["lbl"].winfo_exists():
                    return
            except Exception:
                pass
        if old is not None and old["lbl"] is not None:
            try:
                old["lbl"].destroy()
            except Exception:
                pass

        crop = self._glass_compose(w, tint, alpha, blur, pbase, rect)
        if crop is None:
            return
        photo = ImageTk.PhotoImage(crop)

        if use_item:
            try:
                canvas.delete("glassbg")
                canvas.create_image(0, 0, anchor="nw", image=photo, tags="glassbg")
            except Exception:
                return
            self._glass_raise(w)
            self._glass_hook_draw(w)
            lbl = None
        else:
            lbl = tk.Label(w, image=photo, bd=0, highlightthickness=0)
            lbl.place(x=0, y=0, relwidth=1, relheight=1)
            try:
                lbl.lower()
            except Exception:
                pass

        placed[w] = {"lbl": lbl, "photo": photo, "key": key,
                     "tint": tint, "alpha": alpha, "blur": blur,
                     "canvas": use_item, "pbase": pbase,
                     "kind": "item" if use_item else "label"}
        self._glass_bind(w)
        self._glass_fix_text(w, self._glass_base(tint, alpha, blur))

    def _glass_blend_color(self, base, rect, color, alpha):
        """把 color 按 alpha 混到 base 的该区域上，返回混合后的颜色"""
        from PIL import Image
        c = self._as_hex(color)
        if c is None:
            return None
        crop = self._glass_crop(base, rect)
        if crop is None:
            return None
        r, g, b = crop.resize((1, 1), Image.BILINEAR).getpixel((0, 0))
        cr, cg, cb = self._rgb(c)
        a = max(0.0, min(1.0, alpha))
        return "#%02X%02X%02X" % (int(round(r + (cr - r) * a)),
                                  int(round(g + (cg - g) * a)),
                                  int(round(b + (cb - b) * a)))

    def _glass_paint_on_canvas(self, w, tint, alpha, blur=False):
        """开关 / 滑块：把玻璃垫在画布最底层，并把「轨道色」也做成半透明。

        它们的轨道（开关的条、滑块的槽）是直接画在画布上的实色图形，
        垫底垫不掉它，所以再把轨道色换成「本色 × 该处背景」的混合色。
        注意：开关/滑块的 fg_color 是【轨道色】，不是面板底色，
        不能拿它当控件底色用（否则开关周围会出现一块和轨道同色的底）。
        """
        from PIL import ImageTk
        canvas = getattr(w, "_canvas", None)
        if canvas is None:
            return
        try:
            if not canvas.winfo_exists() or not w.winfo_ismapped():
                return
        except Exception:
            return
        rect = self._glass_rect(w)
        if rect[2] < 2 or rect[3] < 2:
            return
        key = ("C", tint, round(alpha, 3), bool(blur), rect)
        placed = getattr(self, "_glass_placed", None)
        if placed is None:
            placed = {}
            self._glass_placed = placed
        base = self._glass_base(tint, alpha, blur)
        old = placed.get(w)
        if old is None or old["key"] != key:
            crop = self._glass_crop(base, rect)
            if crop is not None:
                photo = ImageTk.PhotoImage(crop)
                try:
                    canvas.delete("glassbg")
                    canvas.create_image(0, 0, anchor="nw", image=photo, tags="glassbg")
                    canvas.tag_lower("glassbg")
                    placed[w] = {"lbl": None, "photo": photo, "key": key,
                                 "tint": tint, "alpha": alpha, "blur": blur,
                                 "canvas": True, "kind": "under"}
                except Exception:
                    return
        # 轨道 / 槽的颜色也变半透明。
        # 注意：一定要从【原始色】混合，不能拿当前值再混一次 ——
        # 那样每重画一次就离背景更近一点，开/关最后会变成同一个颜色。
        orig = getattr(self, "_glass_color_orig", None)
        if orig is None:
            orig = {}
            self._glass_color_orig = orig
        saved = orig.get(w)
        props = {}
        for name in ("fg_color", "progress_color"):
            try:
                cur = w.cget(name)
            except Exception:
                continue
            if not cur:
                continue
            base_col = saved.get(name, cur) if saved else cur
            new = self._glass_blend_color(base, rect, base_col, alpha)
            if new:
                props[name] = new
        if not props:
            return
        if saved is None:
            try:
                orig[w] = {k: w.cget(k) for k in props}
            except Exception:
                orig[w] = {}
        # 只在颜色真的不一样时才设 —— 无条件 configure 会触发重绘，
        # 重绘又回到这里，会死循环
        try:
            if all(str(w.cget(k)) == str(v) for k, v in props.items()):
                return
        except Exception:
            pass
        try:
            w.configure(**props)
        except Exception:
            pass

    def _glass_fix_scrollregion(self, cv, frame):
        """把可滚动区域的范围重新设成「内容」的大小。

        坑：我们在滚动视口上贴了一张和视口一样大的玻璃图（画布上的一项），
        而 CustomTkinter 是用 bbox("all")（画布上所有项的并集）当滚动范围的，
        于是滚动范围被这张图撑成了「视口大小」——
        内容只比视口高一点点时就刚好相等，结果是「内容明明超出去却滚不动」。
        这里把滚动范围改回按「内容」算。
        """
        try:
            item = getattr(frame, "_create_window_id", None)
            bb = cv.bbox(item) if item else None
            if not bb:
                return
            cv.configure(scrollregion=bb)
        except Exception:
            pass

    def _glass_bind_scrollregion(self, frame):
        """给可滚动区域挂上「重算滚动范围」的回调（在 CustomTkinter 之后执行）"""
        if getattr(frame, "_glass_sr_bound", False):
            return
        try:
            cv = getattr(frame, "_parent_canvas", None)
            if cv is None:
                return
            frame._glass_sr_bound = True
            frame.bind("<Configure>",
                       lambda e, f=frame, c=cv: self._glass_fix_scrollregion(c, f), add="+")
            cv.bind("<Configure>",
                    lambda e, f=frame, c=cv: self._glass_fix_scrollregion(c, f), add="+")
        except Exception:
            pass

    def _glass_paint_viewport(self, cv, tint, alpha, blur=False):
        """普通 tk 画布（可滚动区域的视口）：把图作为画布最底层的一项。

        画布会被滚动，所以图要按「视口原点」的坐标摆，滚动时再跟着挪。
        """
        from PIL import ImageTk
        try:
            if not cv.winfo_exists() or not cv.winfo_ismapped():
                return
        except Exception:
            return
        rect = self._glass_rect(cv)
        if rect[2] < 2 or rect[3] < 2:
            return
        key = ("V", tint, round(alpha, 3), bool(blur), rect)
        placed = getattr(self, "_glass_placed", None)
        if placed is None:
            placed = {}
            self._glass_placed = placed
        old = placed.get(cv)
        if old is not None and old["key"] == key:
            self._glass_reposition_viewport(cv)
            return
        crop = self._glass_crop(self._glass_base(tint, alpha, blur), rect)
        if crop is None:
            return
        photo = ImageTk.PhotoImage(crop)
        try:
            cv.delete("glassbg")
            cv.create_image(cv.canvasx(0), cv.canvasy(0), anchor="nw",
                            image=photo, tags="glassbg")
            cv.tag_lower("glassbg")
        except Exception:
            return
        placed[cv] = {"lbl": None, "photo": photo, "key": key,
                      "tint": tint, "alpha": alpha, "blur": blur,
                      "canvas": True, "viewport": True, "kind": "viewport"}

    def _glass_reposition_viewport(self, cv):
        try:
            cv.coords("glassbg", cv.canvasx(0), cv.canvasy(0))
        except Exception:
            pass
        # 贴的这张图会被 CustomTkinter 算进滚动范围（bbox("all")），
        # 滚动时它跟着挪，滚动范围就会被越撑越大，表现就是滚不动/乱滚。
        # 所以每次挪完都把滚动范围重新按「内容」设一遍。
        f = getattr(cv, "_glass_frame", None)
        if f is not None:
            self._glass_fix_scrollregion(cv, f)

    def _glass_bind(self, w):
        if getattr(w, "_glass_bound", False):
            return
        try:
            w._glass_bound = True
            w.bind("<Configure>", lambda e, ww=w: self._glass_dirty(ww), add="+")
        except Exception:
            pass

    def _glass_dirty(self, w):
        if getattr(self, "_bg_busy", False) or not getattr(self, "_bg_img", None):
            return
        if getattr(self, "_glass_after", None) is None:
            dirty = getattr(self, "_glass_dirty_set", None)
            if dirty is None:
                dirty = set()
                self._glass_dirty_set = dirty
            dirty.add(w)
            try:
                self._glass_after = self.after(25, self._glass_flush)
            except Exception:
                pass
        else:
            dirty = getattr(self, "_glass_dirty_set", None)
            if dirty is None:
                dirty = set()
                self._glass_dirty_set = dirty
            dirty.add(w)

    def _glass_flush(self):
        """把这一轮动过的控件重贴一遍"""
        self._glass_after = None
        dirty = getattr(self, "_glass_dirty_set", set())
        self._glass_dirty_set = set()
        if getattr(self, "_bg_busy", False):
            return
        placed = getattr(self, "_glass_placed", {})
        for w in list(dirty):
            info = placed.get(w)
            try:
                if not w.winfo_exists():
                    placed.pop(w, None)
                    continue
            except Exception:
                placed.pop(w, None)
                continue
            if info is None:
                continue
            try:
                k = info.get("kind")
                if k == "viewport":
                    self._glass_paint_viewport(w, info["tint"], info["alpha"], info.get("blur", False))
                elif k == "under":
                    self._glass_paint_on_canvas(w, info["tint"], info["alpha"])
                else:
                    self._glass_paint(w, info["tint"], info["alpha"],
                                      info.get("blur", False), info.get("pbase"))
            except Exception:
                pass
        # 可滚动区域滚过之后，视口底图要跟着挪回原位
        for w, info in list(placed.items()):
            if info.get("kind") == "viewport":
                self._glass_reposition_viewport(w)

    @staticmethod
    def _children_of(w):
        """安全地拿子控件。

        CustomTkinter 覆盖了 _root，tkinter 的 winfo_children() 偶尔会
        抛 TypeError('MainApp' object is not callable)，那样整棵子树都会被漏掉。
        出错时退回读 children 字典（tkinter 自己维护的，不经过 _root）。
        """
        try:
            return list(w.winfo_children())
        except Exception:
            pass
        try:
            out = []
            for c in list(w.children.values()):
                try:
                    if c.winfo_exists():
                        out.append(c)
                except Exception:
                    pass
            return out
        except Exception:
            return []

    def _glass_walk(self, parent, tint, alpha, panel_alpha, blur=False, depth=0):
        if depth > 16:
            return
        children = self._children_of(parent)
        if not children:
            return
        # 这一层「底下」的玻璃（子控件切圆角时要用它来补圆角外面）
        pbase = self._glass_base(tint, alpha, blur)
        sidebar = getattr(self, "sidebar", None)
        for w in children:
            cls = type(w).__name__
            # 不可见（比如其它页面）整棵跳过：全app有七百多个控件，
            # 每次贴图都白走一遍很费时间
            try:
                if not w.winfo_ismapped():
                    continue
            except Exception:
                continue
            # 是不是 CustomTkinter 的控件：类名带 CTk，或者带 _fg_color。
            # 两个都要判 —— FloatingDropdown / Accordion 是自己继承的类（名字不带
            # CTk，但有 _fg_color），而 CTkScrollableFrame 只管着内部一个 frame，
            # 名字带 CTk 却没有 _fg_color。只判一个都会漏掉整块。
            if cls.startswith("CTk") or hasattr(w, "_fg_color"):
                if cls == "CTkCanvas":
                    continue
            elif cls in ("Canvas", "Frame", "Toplevel"):
                # 普通 tk 容器（可滚动框架内部就是这种画布）：只往下走，不贴图，
                # 否则里面的控件（设置页整页）都会漏掉
                if cls == "Canvas":
                    try:
                        self._glass_paint_viewport(w, tint, alpha, blur)
                    except Exception:
                        pass
                self._glass_walk(w, tint, alpha, panel_alpha, blur, depth + 1)
                continue
            else:
                continue
            # 侧边栏整块走「模糊」那条线
            _blur = blur or (w is sidebar and bool(self.settings.get("sidebar_glass", True)))
            if cls == "CTkScrollableFrame":
                # 可滚动区域：滚动范围要按「内容」算，不能被我们贴的视口图撑大
                self._glass_bind_scrollregion(w)
                cv2 = getattr(w, "_parent_canvas", None)
                if cv2 is not None:
                    try:
                        cv2._glass_frame = w
                    except Exception:
                        pass
                    self._glass_fix_scrollregion(cv2, w)
            if cls in self._GLASS_ON_CANVAS:
                # 开关 / 滑块：它们的 fg_color 是【轨道色】不是面板底色，
                # 所以底色用继承下来的那层，轨道色在函数里单独处理
                try:
                    self._glass_paint_on_canvas(w, tint, alpha, _blur)
                except Exception:
                    pass
                self._glass_walk(w, tint, alpha, panel_alpha, _blur, depth + 1)
                continue
            own = self._w_fg(w)
            if own is not None:
                t, a = own, panel_alpha
            else:
                t, a = tint, alpha
            try:
                self._glass_paint(w, t, a, _blur, pbase)
            except Exception:
                pass
            self._glass_walk(w, t, a, panel_alpha, _blur, depth + 1)

    def _apply_background(self):
        """根据设置应用背景：自定义图片 + 半透明面板；没图就是原来的纯色

        已经是增量刷新：图没换、控件没动过的不会重贴，
        否则每切一次页面都要重做一百多张贴图，卡得没法用。
        """
        if getattr(self, "_bg_busy", False):
            return
        self._bg_busy = True
        self._bg_sig = (str(self.settings.get("bg_image") or ""),
                        round(self._glass_alpha(), 3),
                        bool(self.settings.get("sidebar_glass", True)),
                        round(float(self.settings.get("bg_dim", 0.0) or 0.0), 3))
        # 每一轮允许缓存的透明度：只有结构层的 0 和当前面板透明度
        self._glass_cache_alphas = {0.0, round(self._glass_alpha(), 3)}
        _cache = getattr(self, "_glass_cache", None)
        if _cache:
            for _k in [_k for _k in _cache if _k[2] not in self._glass_cache_alphas]:
                _cache.pop(_k, None)
        try:
            img_path = self.settings.get("bg_image")
            has_img = bool(img_path) and Path(img_path).exists()
            if not has_img:
                self._glass_clear()
                self._bg_img = None
                self._bg_key = None
                self._glass_cache = {}
                self._glass_cache_alphas = None
                return

            from PIL import Image, ImageTk
            self.update_idletasks()
            w = max(100, self.winfo_width())
            h = max(100, self.winfo_height())
            _dim = max(0.0, min(0.6, float(self.settings.get("bg_dim", 0.0) or 0.0)))
            key = (str(img_path), w, h, round(_dim, 3))
            if getattr(self, "_bg_key", None) != key or getattr(self, "_bg_img", None) is None:
                # 图或窗口尺寸变了：整体重来一次
                self._glass_clear()
                img = Image.open(img_path).convert("RGB")
                # cover 缩放：铺满窗口并居中裁剪
                scale = max(w / img.width, h / img.height)
                img = img.resize(
                    (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                    Image.LANCZOS,
                )
                x = (img.width - w) // 2
                y = (img.height - h) // 2
                img = img.crop((x, y, x + w, y + h))
                if _dim > 0.001:
                    # 压暗：让文字在花哨的照片背景上也看得清
                    img = Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), _dim)
                self._bg_img = img
                self._bg_key = key
                self._glass_cache = {}
                self._glass_cache_alphas = None

                # 整窗铺一张原图（结构层=完全透明，直接就是原图）
                photo = ImageTk.PhotoImage(self._bg_img)
                self._bg_photos.append(photo)
                lbl = tk.Label(self, image=photo, bd=0, highlightthickness=0)
                lbl.place(x=0, y=0, relwidth=1, relheight=1)
                lbl.lower()
                self._bg_layers.append(lbl)

            # 从窗口往下走：实色面板按「面板透明度」贴玻璃，
            # 透明容器继承上一层的颜色（所以页面空白处还是纯原图）
            self._glass_walk(self, self._as_hex(BG) or "#1C1C1C", 0.0,
                             self._glass_alpha(), False, 0)
            # 已经销毁的控件，把它的记录清掉
            placed = getattr(self, "_glass_placed", {})
            for _w in list(placed):
                try:
                    if not _w.winfo_exists():
                        info = placed.pop(_w)
                        if info.get("lbl") is not None:
                            info["lbl"].destroy()
                except Exception:
                    pass
        except Exception as e:
            # 不要静默失败：写进 data/error.log，方便排查
            # （以前这里被吞掉，导致「背景图没效果」这种问题很难查）
            from errlog import log_exc
            log_exc("背景图")
            print("[背景图] 应用失败:", e)
        finally:
            self._bg_busy = False
