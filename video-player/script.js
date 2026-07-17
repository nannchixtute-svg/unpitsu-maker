/**
 * インタラクティブ動画プレイヤー
 * config.json を読み込み、動画の再生位置に応じてボタンを表示/非表示し、
 * ボタンのアクション（スキップ / 外部リンク）を制御する。
 */
(() => {
  'use strict';

  const CONFIG_URL = 'config.json';
  const HIDE_TRANSITION_MS = 260; // style.css の .overlay-btn transition と合わせる

  const video = document.getElementById('main-video');
  const buttonLayer = document.getElementById('button-layer');
  const playOverlay = document.getElementById('play-overlay');
  const errorBanner = document.getElementById('error-banner');
  const loadingIndicator = document.getElementById('loading-indicator');

  /** @type {{videoUrl:string, autoPauseAt?:number, buttons?:Array}} */
  let config = null;

  // ボタン要素と、対応する config エントリ、現在の表示状態を保持
  /** @type {Array<{el:HTMLButtonElement, def:Object, visible:boolean, hideTimer:number|null}>} */
  const buttonStates = [];

  let autoPauseFired = false;

  function showError(message) {
    errorBanner.textContent = message;
    errorBanner.hidden = false;
  }

  function hideLoading() {
    loadingIndicator.hidden = true;
  }

  async function loadConfig() {
    let response;
    try {
      response = await fetch(CONFIG_URL, { cache: 'no-cache' });
    } catch (networkErr) {
      throw new Error('config.json の取得に失敗しました（ネットワークエラー）。');
    }

    if (!response.ok) {
      throw new Error(`config.json の取得に失敗しました（HTTP ${response.status}）。`);
    }

    let data;
    try {
      data = await response.json();
    } catch (parseErr) {
      throw new Error('config.json の形式が不正です（JSON パースエラー）。');
    }

    if (!data || typeof data.videoUrl !== 'string' || !data.videoUrl) {
      throw new Error('config.json に videoUrl が指定されていません。');
    }

    return data;
  }

  function validateButtonDef(def, index) {
    const errors = [];
    if (typeof def.text !== 'string' || !def.text.trim()) {
      errors.push('text が未指定');
    }
    if (typeof def.showAt !== 'number' || Number.isNaN(def.showAt)) {
      errors.push('showAt が不正');
    }
    if (typeof def.hideAt !== 'number' || Number.isNaN(def.hideAt)) {
      errors.push('hideAt が不正');
    }
    if (def.action !== 'skip' && def.action !== 'link') {
      errors.push('action は "skip" か "link" である必要があります');
    }
    if (def.action === 'skip' && typeof def.targetTime !== 'number') {
      errors.push('action=skip には targetTime(number) が必要です');
    }
    if (def.action === 'link' && typeof def.linkUrl !== 'string') {
      errors.push('action=link には linkUrl(string) が必要です');
    }
    if (errors.length) {
      console.warn(`[config.json] buttons[${index}] を無視しました: ${errors.join(', ')}`, def);
      return false;
    }
    return true;
  }

  function handleButtonClick(def) {
    if (def.action === 'skip') {
      const target = Math.max(0, Number(def.targetTime));
      video.currentTime = target;
      autoPauseFired = typeof config.autoPauseAt === 'number' && target >= config.autoPauseAt;
      // 停止状態から再開するケースをカバー
      const playPromise = video.play();
      if (playPromise && typeof playPromise.catch === 'function') {
        playPromise.catch((err) => {
          console.warn('再生の再開に失敗しました:', err);
        });
      }
    } else if (def.action === 'link') {
      window.open(def.linkUrl, '_blank', 'noopener,noreferrer');
    }
  }

  function createButtonElement(def) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'overlay-btn is-hidden-flow';
    btn.textContent = def.text;
    btn.addEventListener('click', () => handleButtonClick(def));
    return btn;
  }

  function buildButtons(buttonDefs) {
    if (!Array.isArray(buttonDefs)) return;

    buttonDefs.forEach((def, index) => {
      if (!validateButtonDef(def, index)) return;

      const el = createButtonElement(def);
      buttonLayer.appendChild(el);
      buttonStates.push({ el, def, visible: false, hideTimer: null });
    });
  }

  function showButton(state) {
    if (state.visible) return;
    state.visible = true;

    if (state.hideTimer !== null) {
      clearTimeout(state.hideTimer);
      state.hideTimer = null;
    }

    state.el.classList.remove('is-hidden-flow');
    // display:none 解除直後に opacity を変えないとトランジションが発火しないため
    // 次フレームで is-visible を付与する
    requestAnimationFrame(() => {
      state.el.classList.add('is-visible');
    });
  }

  function hideButton(state) {
    if (!state.visible) return;
    state.visible = false;

    state.el.classList.remove('is-visible');
    state.hideTimer = window.setTimeout(() => {
      state.el.classList.add('is-hidden-flow');
      state.hideTimer = null;
    }, HIDE_TRANSITION_MS);
  }

  function updateButtonsVisibility(currentTime) {
    buttonStates.forEach((state) => {
      const { showAt, hideAt } = state.def;
      const shouldShow = currentTime >= showAt && currentTime < hideAt;
      if (shouldShow) {
        showButton(state);
      } else {
        hideButton(state);
      }
    });
  }

  function handleTimeUpdate() {
    const currentTime = video.currentTime;
    updateButtonsVisibility(currentTime);

    if (
      typeof config.autoPauseAt === 'number' &&
      !autoPauseFired &&
      currentTime >= config.autoPauseAt
    ) {
      autoPauseFired = true;
      video.pause();
    }
  }

  function resetAutoPauseGuard() {
    // シーク等で autoPauseAt 未満に戻った場合は再度発火できるようにする
    if (typeof config.autoPauseAt !== 'number') return;
    if (video.currentTime < config.autoPauseAt) {
      autoPauseFired = false;
    }
  }

  function setupPlayOverlay() {
    const syncOverlay = () => {
      playOverlay.classList.toggle('is-hidden', !video.paused && !video.ended);
    };

    playOverlay.addEventListener('click', () => {
      const playPromise = video.play();
      if (playPromise && typeof playPromise.catch === 'function') {
        playPromise.catch((err) => {
          console.warn('再生の開始に失敗しました:', err);
          showError('動画の再生を開始できませんでした。画面をタップしてもう一度お試しください。');
        });
      }
    });

    video.addEventListener('play', syncOverlay);
    video.addEventListener('playing', syncOverlay);
    video.addEventListener('pause', syncOverlay);
    video.addEventListener('ended', syncOverlay);
    syncOverlay();
  }

  async function init() {
    try {
      config = await loadConfig();
    } catch (err) {
      hideLoading();
      showError(err.message || '設定の読み込み中に不明なエラーが発生しました。');
      console.error(err);
      return;
    }

    video.src = config.videoUrl;
    buildButtons(config.buttons);
    setupPlayOverlay();

    video.addEventListener('loadeddata', hideLoading, { once: true });
    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('seeked', resetAutoPauseGuard);

    video.addEventListener('error', () => {
      hideLoading();
      const mediaError = video.error;
      const detail = mediaError ? `（コード: ${mediaError.code}）` : '';
      showError(`動画ファイルを読み込めませんでした ${detail}`);
    });

    video.load();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
