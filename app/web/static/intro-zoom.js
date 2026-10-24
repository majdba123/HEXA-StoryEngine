/* Intro Zoom web operator. No image recognition; user's click is authoritative. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {image: null, voice: null, url: null, point: null, natural: null, ready: false};
  const enabled = () => $('intro-enabled').checked;
  const show = (id, value) => { $(id).hidden = !value; };
  const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
  function rect() {
    if (!state.natural) return null;
    const box = $('intro-image-area').getBoundingClientRect();
    const w = state.natural.width, h = state.natural.height;
    const scale = Math.min(box.width / w, box.height / h);
    return {box, x: (box.width - w * scale) / 2, y: (box.height - h * scale) / 2,
            width: w * scale, height: h * scale};
  }
  function mark() {
    const area = rect();
    show('intro-target', Boolean(state.point && area));
    if (!state.point || !area) return;
    $('intro-target').style.left = (area.x + state.point.x * area.width) + 'px';
    $('intro-target').style.top = (area.y + state.point.y * area.height) + 'px';
  }
  function preview(canvasId) {
    const canvas = $(canvasId), ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!state.natural || !state.point) return;
    const source = $('intro-image-preview'), w = source.naturalWidth, h = source.naturalHeight;
    const ratio = canvas.width / canvas.height;
    const magnification = Number($('intro-magnification').value) / 100;
    const baseW = Math.min(w, h * ratio), baseH = baseW / ratio;
    const cropW = baseW / magnification, cropH = baseH / magnification;
    const x = state.point.x * w - cropW / 2, y = state.point.y * h - cropH / 2;
    // Match backend's intentionally blurred contain fill when a crop crosses an image edge.
    ctx.fillStyle = '#131820'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    const scale = Math.min(canvas.width / w, canvas.height / h);
    ctx.drawImage(source, (canvas.width - w * scale) / 2,
                  (canvas.height - h * scale) / 2, w * scale, h * scale);
    const destX = -x / cropW * canvas.width, destY = -y / cropH * canvas.height;
    ctx.drawImage(source, destX, destY, w / cropW * canvas.width, h / cropH * canvas.height);
  }
  function refresh() {
    $('intro-zoom-value').textContent = (Number($('intro-magnification').value) / 100).toFixed(2) + '×';
    mark(); preview('intro-preview-youtube'); preview('intro-preview-reels');
    state.ready = Boolean(state.image && state.voice && state.point);
  }
  function clearImage() {
    if (state.url) URL.revokeObjectURL(state.url);
    state.url = null; state.point = null; state.image = null; state.natural = null;
    $('intro-image-preview').removeAttribute('src');
    show('intro-image-preview', false);
    $('intro-selection-status').textContent = 'ارفع الصورة واضغط على منتصف الدائرة المطلوبة.';
    refresh();
  }
  $('intro-enabled').addEventListener('change', () => {
    show('intro-fields', enabled());
    if (!enabled()) clearImage();
  });
  $('intro-image').addEventListener('change', () => {
    clearImage();
    const file = $('intro-image').files[0];
    if (!file) return;
    if (!/\.(png|jpe?g|webp)$/i.test(file.name) || file.size > 200 * 1048576) {
      $('intro-image').value = ''; $('intro-selection-status').textContent = 'صورة غير مدعومة أو كبيرة جدًا.'; return;
    }
    state.url = URL.createObjectURL(file);
    const image = $('intro-image-preview');
    image.onload = () => {
      if (image.naturalWidth < 32 || image.naturalHeight < 32 ||
          image.naturalWidth * image.naturalHeight > 48000000) {
        $('intro-selection-status').textContent = 'أبعاد الصورة غير مدعومة.'; clearImage(); return;
      }
      state.image = file;
      state.natural = {width:image.naturalWidth,height:image.naturalHeight};
      show('intro-image-preview', true); refresh();
    };
    image.onerror = () => {
      $('intro-selection-status').textContent = 'تعذر قراءة صورة الافتتاحية.'; clearImage();
    };
    image.src = state.url;
  });
  $('intro-image-area').addEventListener('click', event => {
    const area = rect();
    if (!area) return;
    const x = event.clientX - area.box.left - area.x;
    const y = event.clientY - area.box.top - area.y;
    if (x < 0 || y < 0 || x >= area.width || y >= area.height) return;
    state.point = {x:clamp(x / area.width,0,1), y:clamp(y / area.height,0,1)};
    $('intro-selection-status').textContent = 'تم حفظ موقع الأيقونة ✓';
    refresh();
  });
  $('intro-magnification').addEventListener('input', refresh);
  $('intro-voice').addEventListener('change', () => {
    const file = $('intro-voice').files[0];
    state.voice = null;
    if (!file) { $('intro-voice-status').textContent = 'الصوت لم يُختَر بعد.'; return; }
    if (!/\.(wav|mp3|m4a|aac|flac|ogg)$/i.test(file.name) || file.size > 64 * 1048576) {
      $('intro-voice').value = ''; $('intro-voice-status').textContent = 'صيغة الصوت أو حجمه غير مدعوم.'; return;
    }
    // Server ffprobe/ffmpeg remains authoritative on decoded duration (<=3 seconds).
    const clip = document.createElement('audio');
    const url = URL.createObjectURL(file);
    clip.preload = 'metadata';
    clip.onloadedmetadata = () => {
      URL.revokeObjectURL(url);
      if (Number.isFinite(clip.duration) && clip.duration > 3.0) {
        $('intro-voice').value = ''; $('intro-voice-status').textContent = 'الصوت أطول من 3 ثوانٍ.';
      } else {
        state.voice = file; $('intro-voice-status').textContent = 'تم اختيار الصوت؛ سيتحقق السيرفر من مدته ✓';
      }
      refresh();
    };
    clip.onerror = () => { URL.revokeObjectURL(url); state.voice = file;
      $('intro-voice-status').textContent = 'سيتحقق السيرفر من الصوت ومدته قبل التوليد.'; refresh(); };
    clip.src = url;
  });
  const selections = () => state.point && ({focus_x:state.point.x,focus_y:state.point.y,
      magnification:Number($('intro-magnification').value)/100});
  window.HEXAIntroZoom = {
    lock(value) {
      ['intro-enabled','intro-image','intro-voice','intro-magnification'].forEach(id => { $(id).disabled = value; });
    },
    files(output) {
      if (!enabled()) return [];
      if (output !== 'VIDEO') throw Error('افتتاحية Intro Zoom متاحة للفيديو MP4 فقط، وليس Premiere.');
      if (!state.ready) throw Error('اختر صورة الافتتاحية، اضغط على الدائرة، وارفع صوتًا حتى 3 ثوانٍ.');
      return [
        {id:'intro_image',path:state.image.name,role:'intro_image',file:state.image},
        {id:'intro_audio',path:state.voice.name,role:'intro_audio',file:state.voice}
      ];
    },
    choice(output) {
      if (!enabled()) return null;
      if (output !== 'VIDEO' || !state.ready) throw Error('أكمل تحديد افتتاحية الفيديو أولاً.');
      return selections();
    }
  };
  window.addEventListener('resize', mark);
})();
