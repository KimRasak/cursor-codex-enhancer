#!/usr/bin/env python3
"""
Cursor / VS Code OpenAI Codex Extension Enhancer (patch.py)

Enhances the official `openai.chatgpt` (Codex) extension in Cursor / VS Code with:
1. Collapsible & Dockable Session Sidebar (Cmd/Ctrl + B)
2. Resizable Sidebar Width (drag right border, double-click to reset)
3. Full Session Pinning (Pin / Unpin persisted to globalState + localStorage)
4. Drag-and-Drop Session Reordering (within Pinned, within Recent, and cross-group)
5. Compact Recent Sessions Section (default 3 items, collapsible, Show More toggle)
6. Normal IDE Font Size (13px UI / 12px Code) + Header A-/A+ Font Size Controller
7. Cursor Activity Bar / Secondary Sidebar compatibility fix in package.json

Usage:
  python3 patch.py            # Apply all enhancements
  python3 patch.py --status   # Check current patch status
  python3 patch.py --revert   # Revert all changes from backups
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKUP_SUFFIX = ".bak.codex-enhancer"
LEGACY_BACKUP_SUFFIX = ".bak.20261118-sidebar-pin"
MARKER = "_SIDEBAR_WIDTH_KEY"


def find_extension_dir(custom_dir: str | None = None) -> Path:
    if custom_dir:
        p = Path(custom_dir).expanduser().resolve()
        if not p.is_dir():
            sys.exit(f"[ERROR] Extension directory not found: {p}")
        return p

    home = Path.home()
    for root in [home / ".cursor" / "extensions", home / ".vscode" / "extensions"]:
        if root.is_dir():
            candidates = [
                match for match in root.glob("openai.chatgpt-*")
                if match.is_dir() and (match / "out" / "extension.js").is_file()
            ]
            if candidates:
                candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                return candidates[0]

    sys.exit(
        "[ERROR] Could not find `openai.chatgpt-*` under ~/.cursor/extensions or ~/.vscode/extensions.\n"
        "Use `--ext-dir /path/to/openai.chatgpt-*` to specify it manually."
    )


def ensure_backup(file_path: Path) -> Path:
    bak_path = file_path.with_name(file_path.name + BACKUP_SUFFIX)
    legacy_bak = file_path.with_name(file_path.name + LEGACY_BACKUP_SUFFIX)
    if not bak_path.exists():
        if legacy_bak.exists():
            shutil.copy2(legacy_bak, bak_path)
        else:
            shutil.copy2(file_path, bak_path)
    return bak_path


def find_single_asset(assets_dir: Path, pattern: str) -> Path:
    matches = sorted(
        p for p in assets_dir.glob(pattern)
        if not p.name.endswith(".map") and ".bak" not in p.name
    )
    if not matches:
        sys.exit(f"[ERROR] Asset matching `{pattern}` not found in {assets_dir}")
    # Prefer the largest file if there is a thin re-export wrapper (like header-*.js)
    matches.sort(key=lambda p: p.stat().st_size, reverse=True)
    return matches[0]


def patch_package_json(ext_dir: Path) -> bool:
    pkg_path = ext_dir / "package.json"
    if not pkg_path.is_file():
        return False
    ensure_backup(pkg_path)
    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    vc = data.get("contributes", {}).get("viewsContainers", {})
    sec = vc.pop("secondarySidebar", None)
    if sec:
        act = vc.setdefault("activitybar", [])
        existing_ids = {item.get("id") for item in act if isinstance(item, dict)}
        for item in sec:
            if isinstance(item, dict) and item.get("id") not in existing_ids:
                act.append(item)
        pkg_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True
    return False


def patch_extension_js(ext_dir: Path) -> None:
    ext_js = ext_dir / "out" / "extension.js"
    bak = ensure_backup(ext_js)
    txt = bak.read_text(encoding="utf-8")

    old_handlers = (
        '"list-pinned-threads":async()=>({threadIds:[]}),'
        '"set-thread-pinned":async()=>({success:!1}),'
        '"set-pinned-threads-order":async()=>({success:!1}),'
    )
    new_handlers = (
        '"list-pinned-threads":async()=>{'
        'let e=await this.globalState.get(de.PINNED_THREAD_IDS),'
        'r=Array.isArray(e)?e.filter(n=>typeof n=="string"):[];'
        'return{threadIds:r,serverOrderedThreadIds:r}},'
        '"set-thread-pinned":async({threadId:e,pinned:r,beforeThreadId:n})=>{'
        'if(typeof e!="string"||!e)return{success:!1};'
        'let o=await this.globalState.get(de.PINNED_THREAD_IDS),'
        'i=(Array.isArray(o)?o.filter(s=>typeof s=="string"):[]).filter(s=>s!==e);'
        'if(r){let s=typeof n=="string"?i.indexOf(n):-1;s>=0?i.splice(s,0,e):n===null?i.push(e):i.unshift(e)}'
        'await this.globalState.update(de.PINNED_THREAD_IDS,i);return{success:!0}},'
        '"set-pinned-threads-order":async({threadIds:e})=>{'
        'let r=Array.isArray(e)?e.filter(n=>typeof n=="string"):[];'
        'await this.globalState.update(de.PINNED_THREAD_IDS,r);return{success:!0}},'
    )
    if old_handlers not in txt:
        sys.exit("[ERROR] Could not locate `list-pinned-threads` handler stub in out/extension.js")
    txt = txt.replace(old_handlers, new_handlers, 1)

    old_sub = 'this.globalState.onDidResetPersistedAtoms(()=>{this.broadcastToAllViews({type:"persisted-atom-sync",state:{}})}))'
    new_sub = (
        'this.globalState.onDidResetPersistedAtoms(()=>{this.broadcastToAllViews({type:"persisted-atom-sync",state:{}})}),'
        'this.globalState.onDidUpdateEntry(({key:he})=>{he===de.PINNED_THREAD_IDS&&this.broadcastToAllViews({type:"pinned-threads-updated"})}))'
    )
    if old_sub in txt:
        txt = txt.replace(old_sub, new_sub, 1)

    # Force Codex to use the primary Left Sidebar (codexViewContainer) instead of Right Secondary Sidebar
    old_sec_check = "function lI(t){let e=ayt(t);return e==null?!1:e.major!==rj.major?e.major>rj.major:e.minor>=rj.minor}"
    new_sec_check = "function lI(t){return!1}"
    if old_sec_check in txt:
        txt = txt.replace(old_sec_check, new_sec_check, 1)

    ext_js.write_text(txt, encoding="utf-8")


def patch_local_conversation_thread(assets_dir: Path) -> Path:
    loc_js = find_single_asset(assets_dir, "local-conversation-thread-*.js")
    bak = ensure_backup(loc_js)
    txt = bak.read_text(encoding="utf-8")
    if "canPin:!1" not in txt:
        sys.exit(f"[ERROR] Could not find `canPin:!1` in {loc_js.name}")
    txt = txt.replace("canPin:!1", "canPin:!0")
    loc_js.write_text(txt, encoding="utf-8")
    return loc_js


def patch_index_html(ext_dir: Path) -> Path:
    idx_html = ext_dir / "webview" / "index.html"
    bak = ensure_backup(idx_html)
    txt = bak.read_text(encoding="utf-8")
    init_style = """    <style id="codex-cursor-font-override">
      :root, :root[data-codex-window-type=extension], ._responseTypography_1wef0_1 {
        font-size: 13px !important;
        --font-ui-size: 13px !important;
        --font-code-size: 12px !important;
        --codex-chat-font-size-override: 13px !important;
        --codex-chat-code-font-size-override: 12px !important;
        --codex-chat-font-size: 13px !important;
        --codex-chat-code-font-size: 12px !important;
        --text-base: 13px !important;
        --text-sm: 12px !important;
        --text-xs: 11px !important;
        --text-lg: 14px !important;
        --text-xl: 16px !important;
        --text-2xl: 18px !important;
        --text-heading-lg: 16px !important;
        --text-heading-md: 15px !important;
        --text-heading-sm: 14px !important;
        --padding-row-y: 2px !important;
        --height-token-nav-row: 26px !important;
        --height-token-row: 26px !important;
      }
      ._RichTextInput_88kve_2 .ProseMirror[data-composer-markdown] h1 {
        font-size: 15px !important;
        margin-block-end: 2px !important;
      }
    </style>
  </head>"""
    txt = txt.replace("  </head>", init_style, 1)
    idx_html.write_text(txt, encoding="utf-8")
    return idx_html


def patch_header_js(assets_dir: Path) -> Path:
    hdr_js = find_single_asset(assets_dir, "header-*.js")
    bak = ensure_backup(hdr_js)
    txt = bak.read_text(encoding="utf-8")

    # 1. Add Wit as _reactDomMod
    old_imp1 = "Vj as s,aq as c,"
    new_imp1 = "Vj as s,Wit as _reactDomMod,aq as c,"
    if old_imp1 not in txt:
        sys.exit(f"[ERROR] Unexpected import block in {hdr_js.name} (missing `{old_imp1}`)")
    txt = txt.replace(old_imp1, new_imp1, 1)

    # 2. Add pinned thread exports
    old_imp2 = "Bat as D,CC as O,"
    new_imp2 = "Ak as _initSidebarPin,Bat as D,CC as O,f0 as _pinnedThreadsAtom,jk as _setThreadPinned,u0 as _initPinnedThreads,"
    if old_imp2 not in txt:
        sys.exit(f"[ERROR] Unexpected import block in {hdr_js.name} (missing `{old_imp2}`)")
    txt = txt.replace(old_imp2, new_imp2, 1)

    # 3. Replace At(e)
    idx1 = txt.find("function At(e){")
    idx2 = txt.find("function jt(){window.dispatchEvent(new CustomEvent(`open-recent-tasks-menu`))}")
    if idx1 == -1 or idx2 == -1:
        sys.exit(f"[ERROR] Could not locate `function At(e)` in {hdr_js.name}")

    new_at_block = """var _ReactDOM,_PIN_STORAGE_KEY=`codex.cursor.pinnedThreadIds`,_SIDEBAR_OPEN_KEY=`codex.cursor.sidebarOpen`,_SIDEBAR_DOCK_KEY=`codex.cursor.sidebarDocked`,_FONT_SIZE_KEY=`codex.cursor.fontSizePx`,_DEFAULT_FONT_SIZE=13,_RECENT_ORDER_KEY=`codex.cursor.recentOrderIds`;
function _readFontSize(){try{let v=Number(localStorage.getItem(_FONT_SIZE_KEY));return Number.isFinite(v)&&v>=11&&v<=18?Math.round(v):_DEFAULT_FONT_SIZE}catch{return _DEFAULT_FONT_SIZE}}
function _applyFontSizeCss(sz){
  if(typeof document>`u`)return;
  let codeSz=Math.max(10,sz-1),smSz=Math.max(11,sz-1),xsSz=Math.max(10,sz-2),
      el=document.getElementById(`codex-cursor-font-override`);
  if(!el){el=document.createElement(`style`),el.id=`codex-cursor-font-override`,document.head.appendChild(el)}
  el.textContent=`:root, :root[data-codex-window-type=extension], ._responseTypography_1wef0_1 {
    font-size: ${sz}px !important;
    --font-ui-size: ${sz}px !important;
    --font-code-size: ${codeSz}px !important;
    --codex-chat-font-size-override: ${sz}px !important;
    --codex-chat-code-font-size-override: ${codeSz}px !important;
    --codex-chat-font-size: ${sz}px !important;
    --codex-chat-code-font-size: ${codeSz}px !important;
    --text-base: ${sz}px !important;
    --text-sm: ${smSz}px !important;
    --text-xs: ${xsSz}px !important;
    --text-lg: ${sz+1}px !important;
    --text-xl: ${sz+3}px !important;
    --text-2xl: ${sz+5}px !important;
    --text-heading-lg: ${sz+3}px !important;
    --text-heading-md: ${sz+2}px !important;
    --text-heading-sm: ${sz+1}px !important;
  }
  ._RichTextInput_88kve_2 .ProseMirror[data-composer-markdown] h1 {
    font-size: ${sz+2}px !important;
    margin-block-end: 2px !important;
  }
  :root[data-codex-window-type=extension] {
    --padding-row-y: 2px !important;
    --height-token-nav-row: 26px !important;
    --height-token-row: 26px !important;
  }
  [data-codex-drop-pos="before"] {
    box-shadow: inset 0 2px 0 0 #3b82f6 !important;
  }
  [data-codex-drop-pos="after"] {
    box-shadow: inset 0 -2px 0 0 #3b82f6 !important;
  }`;
}
function _writeFontSize(sz){
  let clamped=Math.max(11,Math.min(18,Math.round(sz)));
  try{localStorage.setItem(_FONT_SIZE_KEY,String(clamped))}catch{}
  _applyFontSizeCss(clamped);
  if(typeof window<`u`)window.dispatchEvent(new CustomEvent(`codex-cursor-fontsize-updated`,{detail:clamped}));
  return clamped;
}
if(typeof document<`u`)_applyFontSizeCss(_readFontSize());
function _readLocalPins(){try{let e=JSON.parse(localStorage.getItem(_PIN_STORAGE_KEY)||`[]`);return Array.isArray(e)?e.filter(t=>typeof t==`string`):[]}catch{return[]}}
function _writeLocalPins(e){try{let t=Array.from(new Set(e.filter(n=>typeof n==`string`&&n.length>0)));localStorage.setItem(_PIN_STORAGE_KEY,JSON.stringify(t)),window.dispatchEvent(new CustomEvent(`codex-cursor-pins-updated`,{detail:t}))}catch{}}
function _readRecentOrder(){try{let e=JSON.parse(localStorage.getItem(_RECENT_ORDER_KEY)||`[]`);return Array.isArray(e)?e.filter(t=>typeof t==`string`):[]}catch{return[]}}
function _writeRecentOrder(e){try{let t=Array.from(new Set(e.filter(n=>typeof n==`string`&&n.length>0)));localStorage.setItem(_RECENT_ORDER_KEY,JSON.stringify(t)),window.dispatchEvent(new CustomEvent(`codex-cursor-recent-order-updated`,{detail:t}))}catch{}}
function _insertRelative(list,itemId,targetId,pos){
  let arr=list.filter(x=>x!==itemId);
  if(!targetId){arr.push(itemId);return arr}
  let idx=arr.indexOf(targetId);
  if(idx===-1){arr.push(itemId);return arr}
  arr.splice(pos===`before`?idx:idx+1,0,itemId);
  return arr;
}
function _sortByRecentOrder(items,getId,orderIds){
  if(!orderIds||orderIds.length===0)return items;
  let orderMap=new Map(orderIds.map((id,idx)=>[id,idx])),fresh=[],ordered=[];
  for(let it of items){
    let id=getId(it);
    id&&orderMap.has(id)?ordered.push(it):fresh.push(it);
  }
  ordered.sort((a,b)=>(orderMap.get(getId(a))??0)-(orderMap.get(getId(b))??0));
  return[...fresh,...ordered];
}
var _didSeedPins=!1;
function _usePinnedThreads(){
  let e=l(Pe),t=b(_pinnedThreadsAtom),data=t?.data,[r,i]=(0,kn.useState)(()=>_readLocalPins()),[recentOrder,setRecentOrder]=(0,kn.useState)(()=>_readRecentOrder());
  (0,kn.useEffect)(()=>{
    let a=()=>i(_readLocalPins()),onRec=()=>setRecentOrder(_readRecentOrder());
    return window.addEventListener(`codex-cursor-pins-updated`,a),window.addEventListener(`codex-cursor-recent-order-updated`,onRec),()=>{
      window.removeEventListener(`codex-cursor-pins-updated`,a),window.removeEventListener(`codex-cursor-recent-order-updated`,onRec);
    };
  },[]);
  (0,kn.useEffect)(()=>{
    if(!data)return;
    let loc=_readLocalPins();
    if(Array.isArray(data.serverOrderedThreadIds)){
      let srv=data.threadIds??[];
      if(!_didSeedPins){
        _didSeedPins=!0;
        if(srv.length===0&&loc.length>0){
          try{e.query.snapshot(_pinnedThreadsAtom).setData({threadIds:loc,serverOrderedThreadIds:loc})}catch{}
          for(let id of [...loc].reverse()){try{_setThreadPinned(e,id,!0)}catch{}}
          return;
        }
      }
      JSON.stringify(srv)!==JSON.stringify(loc)&&_writeLocalPins(srv);
    }else{
      _didSeedPins=!0;
      try{e.query.snapshot(_pinnedThreadsAtom).setData({threadIds:loc,serverOrderedThreadIds:loc})}catch{}
    }
  },[data,e]);
  let s=(0,kn.useMemo)(()=>new Set(r),[r]),c=(0,kn.useCallback)((o,u)=>{
    if(!o)return;
    let d=_readLocalPins(),f=u?[o,...d.filter(p=>p!==o)]:d.filter(p=>p!==o);
    _writeLocalPins(f);
    try{e.query.snapshot(_pinnedThreadsAtom).setData({threadIds:f,serverOrderedThreadIds:f})}catch{}
    try{_setThreadPinned(e,o,u)}catch{}
  },[e]),handleDndDrop=(0,kn.useCallback)(({sourceId,sourceGroup,targetId,targetGroup,position,allUnpinnedIds})=>{
    if(!sourceId||!targetId||sourceId===targetId&&sourceGroup===targetGroup)return;
    if(targetGroup===`pinned`){
      let nextPins=_insertRelative(_readLocalPins(),sourceId,targetId,position),
          newIdx=nextPins.indexOf(sourceId),
          beforeId=newIdx>=0&&newIdx+1<nextPins.length?nextPins[newIdx+1]:null;
      _writeLocalPins(nextPins);
      try{e.query.snapshot(_pinnedThreadsAtom).setData({threadIds:nextPins,serverOrderedThreadIds:nextPins})}catch{}
      try{_setThreadPinned(e,sourceId,!0,beforeId)}catch{}
    }else{
      if(sourceGroup===`pinned`){
        let nextPins=_readLocalPins().filter(p=>p!==sourceId);
        _writeLocalPins(nextPins);
        try{e.query.snapshot(_pinnedThreadsAtom).setData({threadIds:nextPins,serverOrderedThreadIds:nextPins})}catch{}
        try{_setThreadPinned(e,sourceId,!1)}catch{}
      }
      let base=Array.isArray(allUnpinnedIds)&&allUnpinnedIds.length>0?allUnpinnedIds:_readRecentOrder(),
          nextRecent=_insertRelative(base,sourceId,targetId,position);
      _writeRecentOrder(nextRecent);
    }
  },[e]),resetRecentOrder=(0,kn.useCallback)(()=>_writeRecentOrder([]),[]);
  return{pinnedIds:r,pinnedSet:s,togglePin:c,recentOrderIds:recentOrder,handleDndDrop,resetRecentOrder};
}
function _DraggableRow(e){
  let{dndId:id,dndGroup:group,onDropReorder:onDrop,children:ch}=e,ref=(0,kn.useRef)(null);
  let onPointerDown=ev=>{
    if(ev.button!==0||!id||!onDrop)return;
    if(ev.target instanceof Element&&ev.target.closest(`button[aria-label], [data-no-dnd]`))return;
    let rowEl=ref.current;
    if(!rowEl)return;
    let startX=ev.clientX,startY=ev.clientY,dragging=!1,ghostEl=null,lastTargetEl=null,lastPos=null,
        titleText=(rowEl.textContent||``).trim().slice(0,36)||`会话`;
    let clearTarget=()=>{
      if(lastTargetEl){lastTargetEl.removeAttribute(`data-codex-drop-pos`);lastTargetEl=null;lastPos=null}
    };
    let onMove=mev=>{
      let dx=mev.clientX-startX,dy=mev.clientY-startY;
      if(!dragging){
        if(Math.hypot(dx,dy)<5)return;
        dragging=!0;
        rowEl.style.opacity=`0.4`;
        ghostEl=document.createElement(`div`);
        ghostEl.style.cssText=`position:fixed;z-index:99999;pointer-events:none;padding:3px 8px;border-radius:6px;font-size:12px;max-width:220px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:var(--vscode-editorWidget-background,#252526);color:var(--vscode-editorWidget-foreground,#ccc);border:1px solid #3b82f6;box-shadow:0 4px 12px rgba(0,0,0,0.35);`;
        ghostEl.textContent=`⇅ ${titleText}`;
        document.body.appendChild(ghostEl);
      }
      mev.preventDefault();
      if(ghostEl){
        ghostEl.style.left=`${mev.clientX+10}px`;
        ghostEl.style.top=`${mev.clientY-12}px`;
      }
      let under=document.elementFromPoint(mev.clientX,mev.clientY),
          cand=under instanceof Element?under.closest(`[data-codex-dnd-id]`):null;
      clearTarget();
      if(cand&&cand!==rowEl){
        let rect=cand.getBoundingClientRect(),
            pos=mev.clientY<rect.top+rect.height/2?`before`:`after`;
        cand.setAttribute(`data-codex-drop-pos`,pos);
        lastTargetEl=cand;
        lastPos=pos;
      }
    };
    let onUp=()=>{
      window.removeEventListener(`pointermove`,onMove,!0);
      window.removeEventListener(`pointerup`,onUp,!0);
      window.removeEventListener(`pointercancel`,onUp,!0);
      if(!dragging)return;
      rowEl.style.opacity=``;
      ghostEl?.remove();
      let targetEl=lastTargetEl,pos=lastPos;
      clearTarget();
      let suppressClick=cev=>{cev.preventDefault(),cev.stopPropagation()};
      window.addEventListener(`click`,suppressClick,{capture:!0,once:!0});
      setTimeout(()=>window.removeEventListener(`click`,suppressClick,!0),120);
      if(targetEl&&pos){
        let targetId=targetEl.getAttribute(`data-codex-dnd-id`),
            targetGroup=targetEl.getAttribute(`data-codex-dnd-group`)||group;
        targetId&&onDrop({sourceId:id,sourceGroup:group,targetId,targetGroup,position:pos});
      }
    };
    window.addEventListener(`pointermove`,onMove,!0);
    window.addEventListener(`pointerup`,onUp,!0);
    window.addEventListener(`pointercancel`,onUp,!0);
  };
  return(0,Z.jsx)(`div`,{
    ref,
    "data-codex-dnd-id":id,
    "data-codex-dnd-group":group,
    onPointerDown,
    title:`按住上下拖动可调整顺序`,
    className:`group/dnd relative select-none cursor-grab active:cursor-grabbing`,
    children:ch
  });
}
function _PinSvg(e){
  let{filled:t,className:n}=e;
  return(0,Z.jsx)(`svg`,{width:14,height:14,viewBox:`0 0 16 16`,fill:t?`currentColor`:`none`,stroke:`currentColor`,strokeWidth:t?1:1.4,strokeLinecap:`round`,strokeLinejoin:`round`,className:n,"aria-hidden":!0,children:(0,Z.jsx)(`path`,{d:`M9.828 1.172a.5.5 0 0 1 .707 0l4.293 4.293a.5.5 0 0 1 0 .707l-1.414 1.414a.5.5 0 0 1-.566.098l-1.91-.955-2.616 2.616.535 2.675a.5.5 0 0 1-.136.453l-.707.707a.5.5 0 0 1-.707 0L4.768 10.64l-3.182 3.182a.5.5 0 1 1-.707-.707L4.06 9.933 1.52 7.393a.5.5 0 0 1 0-.707l.707-.707a.5.5 0 0 1 .453-.136l2.675.535 2.616-2.616-.955-1.91a.5.5 0 0 1 .098-.566L8.528 1.172z`})});
}
function _ArchiveSvg(e){
  return(0,Z.jsxs)(`svg`,{width:14,height:14,viewBox:`0 0 16 16`,fill:`none`,stroke:`currentColor`,strokeWidth:1.4,strokeLinecap:`round`,strokeLinejoin:`round`,className:e.className,"aria-hidden":!0,children:[(0,Z.jsx)(`rect`,{x:1.5,y:2.5,width:13,height:3,rx:0.8}),(0,Z.jsx)(`path`,{d:`M2.5 5.5v7a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-7`}),(0,Z.jsx)(`path`,{d:`M6.5 8.5h3`})]});
}
function _SidebarSvg(e){
  return(0,Z.jsxs)(`svg`,{width:16,height:16,viewBox:`0 0 16 16`,fill:`none`,stroke:`currentColor`,strokeWidth:1.35,strokeLinecap:`round`,strokeLinejoin:`round`,className:e.className,"aria-hidden":!0,children:[(0,Z.jsx)(`rect`,{x:1.75,y:2.25,width:12.5,height:11.5,rx:2}),(0,Z.jsx)(`line`,{x1:5.75,y1:2.5,x2:5.75,y2:13.5})]});
}
function _RowHoverActions(e){
  let{isPinned:t,onTogglePin:n,onArchive:r,useStableTrailingRail:i}=e;
  return(0,Z.jsxs)(`div`,{
    "data-no-dnd":!0,
    className:`absolute end-0 top-0 z-10 flex h-full items-center justify-end gap-0.5 pe-1.5`,
    style:i?{insetInlineEnd:`var(--task-row-trailing-inset)`}:void 0,
    children:[
      (0,Z.jsx)(`button`,{
        type:`button`,
        title:t?`取消置顶 (Unpin)`:`置顶会话 (Pin)`,
        "aria-label":t?`Unpin chat`:`Pin chat`,
        onClick:a=>{a.preventDefault(),a.stopPropagation(),n()},
        onPointerDown:a=>a.stopPropagation(),
        className:ee(`pointer-events-none flex h-5 w-5 items-center justify-center rounded-md sidebar-hover-icon-tint opacity-0 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-visible:pointer-events-auto group-focus-visible:opacity-100 group-has-[:focus-visible]:pointer-events-auto group-has-[:focus-visible]:opacity-100 focus-visible:pointer-events-auto focus-visible:opacity-100`,t&&`!opacity-90 text-[var(--color-text-info,#3b82f6)]`),
        children:(0,Z.jsx)(_PinSvg,{filled:t,className:`size-3.5`})
      }),
      r!=null?(0,Z.jsx)(`button`,{
        type:`button`,
        title:`归档会话 (Archive)`,
        "aria-label":`Archive chat`,
        onClick:a=>{a.preventDefault(),a.stopPropagation(),r()},
        onPointerDown:a=>a.stopPropagation(),
        className:`pointer-events-none flex h-5 w-5 items-center justify-center rounded-md sidebar-hover-icon-tint opacity-0 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-visible:pointer-events-auto group-focus-visible:opacity-100 group-has-[:focus-visible]:pointer-events-auto group-has-[:focus-visible]:opacity-100 focus-visible:pointer-events-auto focus-visible:opacity-100`,
        children:(0,Z.jsx)(_ArchiveSvg,{className:`size-3.5`})
      }):null
    ]
  });
}
function _itemThreadId(e){
  return e.kind===`remote`?e.task?.id??null:e.conversation?.id??null;
}
function At(e){
  let{mergedTasks:n,tasksQuery:r}=e,i=ve(),a=E(),{cancelPendingWorktree:o}=ie(),{pinnedIds:pIds,pinnedSet:pSet,togglePin:tPin,recentOrderIds:recOrd,handleDndDrop:onDndDrop}=_usePinnedThreads();
  if(r.isLoading&&n.length===0)return null;
  let s=r.error instanceof P&&r.error.status===404;
  if(r.isError&&n.length===0&&!s){
    return(0,Lt.jsxs)(`div`,{className:`mb-2 flex items-center gap-2 text-base text-tertiary`,children:[(0,Lt.jsx)(x,{id:`codex.recentTasksMenu.errorCloud.inline`,defaultMessage:`Failed to load cloud chats.`}),(0,Lt.jsx)(J,{size:`default`,color:`outline`,onClick:()=>r.refetch(),children:(0,Lt.jsx)(x,{id:`codex.common.retry`,defaultMessage:`Retry`})})]});
  }
  if(n.length===0)return null;
  let byId=new Map;
  for(let item of n){let tid=_itemThreadId(item);tid&&byId.set(tid,item)}
  let pinnedItems=pIds.map(id=>byId.get(id)).filter(Boolean),
      attn=n.filter(Pt),
      allUnpinned=_sortByRecentOrder((0,It.default)([...attn,...n],Nt).filter(item=>{let tid=_itemThreadId(item);return!tid||!pSet.has(tid)}),_itemThreadId,recOrd),
      allUnpinnedIds=allUnpinned.map(_itemThreadId).filter(Boolean),
      unpinned=allUnpinned.slice(0,Math.max(4,attn.length)),
      l=[...pinnedItems,...unpinned],
      u=n.length>l.length,
      renderRow=item=>{
        let tid=_itemThreadId(item),isPin=tid!=null&&pSet.has(tid),grp=isPin?`pinned`:`recent`;
        switch(item.kind){
          case`remote`:return(0,Lt.jsx)(_DraggableRow,{dndId:tid,dndGroup:grp,onDropReorder:info=>onDndDrop({...info,allUnpinnedIds}),children:(0,Lt.jsx)(N,{useStableTrailingRail:!0,isActive:a.pathname===`/remote/${item.task.id}`,task:item.task,onClose:Mt})},item.key);
          case`local`:{
            if(item.conversation==null)return(0,Lt.jsx)(B,{useStableTrailingRail:!0,task:item.pendingWorktree,hasAttention:item.pendingWorktree.needsAttention,statusIndicatorReplacesMeta:!0,onArchive:()=>{o(item.pendingWorktree.id)}},item.key);
            let cid=item.conversation.id;
            return(0,Lt.jsx)(_DraggableRow,{
              dndId:cid,
              dndGroup:grp,
              onDropReorder:info=>onDndDrop({...info,allUnpinnedIds}),
              children:(0,Lt.jsx)(Te,{
                useStableTrailingRail:!0,
                isActive:a.pathname===`/local/${cid}`,
                conversationId:cid,
                hostId:item.conversation.hostId,
                statusIndicatorReplacesMeta:!0,
                titlePrefix:isPin?(0,Lt.jsx)(_PinSvg,{filled:!0,className:`size-3 shrink-0 text-[var(--color-text-info,#3b82f6)]`}):void 0,
                additionalHoverActionCount:1,
                renderActions:({archive:arc,requestArchive:reqArc})=>(0,Lt.jsx)(_RowHoverActions,{isPinned:isPin,onTogglePin:()=>tPin(cid,!isPin),onArchive:reqArc??arc,useStableTrailingRail:!0}),
                metaContent:item.conversation.createdAt==null?void 0:(0,Lt.jsx)(ht,{dateString:new Date(item.conversation.createdAt).toISOString()}),
                onActiveArchiveStart:i
              })
            },item.key);
          }
        }
      },
      d=l.map(renderRow),
      f=(0,Lt.jsxs)(`div`,{className:`flex items-center justify-between px-[var(--padding-row-x)] py-1`,children:[
        u?(0,Lt.jsx)(`button`,{type:`button`,className:`cursor-interaction rounded-md text-start text-sm opacity-50 hover:opacity-90`,onClick:jt,children:(0,Lt.jsx)(x,{id:`header.recentTasks.seeAll`,defaultMessage:`View all ({total})`,values:{total:n.length}})}):(0,Lt.jsx)(`span`,{}),
        (0,Lt.jsx)(`button`,{type:`button`,className:`cursor-interaction rounded-md text-end text-xs opacity-50 hover:opacity-90`,onClick:()=>window.dispatchEvent(new CustomEvent(`toggle-codex-cursor-sidebar`)),children:`展开会话侧栏 (⌘B)`})
      ]});
  return(0,Lt.jsxs)(`div`,{className:`group/inline -mx-[var(--padding-row-x)] flex flex-col gap-px rounded-xl pb-1 transition-colors [--task-row-trailing-inset:calc(var(--spacing)*1.5)]`,children:[d,f]});
}
"""
    txt = txt[:idx1] + new_at_block + txt[idx2:]

    # 4. Replace Cn, An, jn
    idx3 = txt.find("function Cn(e){")
    idx4 = txt.find("function Nn(e){")
    if idx3 == -1 or idx4 == -1:
        sys.exit(f"[ERROR] Could not locate `function Cn(e)` in {hdr_js.name}")

    new_cn_block = """var _RECENT_DEFAULT_LIMIT=3;
function Cn(e){
  let{cloudtasksQuery:n,localConversations:r,onClose:i,autoFocusSearch:o,showFilters:s,isSidebar:isSb}=e,
      c=o!==void 0&&o,d=s===void 0||s,f=l(Pe),p=u(),m=ve(),{authMethod:h}=at(),
      g=b(zt)??`recent`,_=b(Bt)??null,v=d?g:`recent`,
      y=a(`/local/:conversationId`)?.params?.conversationId??null,
      {data:S}=Ie(),C=ke(),
      {pinnedIds:pIds,pinnedSet:pSet,togglePin:tPin,recentOrderIds:recOrd,handleDndDrop:onDndDrop,resetRecentOrder}=_usePinnedThreads(),
      [pCollapsed,setPCollapsed]=(0,kn.useState)(!1),
      [rCollapsed,setRCollapsed]=(0,kn.useState)(!1),
      [showAllRecent,setShowAllRecent]=(0,kn.useState)(!1),
      T=d?S?.find(e=>e.id===_)??null:null,
      ee=r.filter(e=>hn({conversation:e,isBackgroundSubagentsEnabled:C})),
      D=_n(n.data,r,T),
      [O,k]=(0,kn.useState)(``),
      A=(0,kn.useDeferredValue)(O).trim().toLowerCase(),
      j=A.length>0,
      M=D.filter(wn),
      P=j?M.filter(e=>V(e.task.title,A)):M,
      F=j?ee.filter(e=>V(Oe(e),A)):ee,
      I=j?D.filter(e=>e.kind===`remote`?V(e.task.title,A):V(e.conversation==null?Tn(e.pendingWorktree,p):Oe(e.conversation),A)):D,
      L=(0,Z.jsx)(He.Section,{children:(0,Z.jsx)(Ht,{searchQuery:O,onQueryChange:k,autoFocus:c})}),
      R=(0,Z.jsx)(`div`,{className:`mx-2 border-t-[0.5px] border-default`,"aria-hidden":!0}),
      z=d&&h===`chatgpt`&&(0,Z.jsxs)(He.Section,{className:`flex items-center justify-between px-[var(--padding-row-x)]`,children:[(0,Z.jsx)(rn,{filter:g,onSelect:e=>f.set(zt,e)}),g!==`local`&&(0,Z.jsx)(Qt,{})]}),
      te=He,
      recentLimit=j||showAllRecent?999:_RECENT_DEFAULT_LIMIT;
  let B=v===`cloud`&&(n.isError?(0,Z.jsx)(Dn,{onRetry:()=>n.refetch()}):n.isLoading?(0,Z.jsx)(En,{}):P.length===0?j?(0,Z.jsx)(dn,{}):(0,Z.jsx)(Kt,{}):P.slice(0,recentLimit).map(e=>(0,Z.jsx)(N,{task:e.task,onClose:i},e.key)));
  let localPinned=[],localUnpinned=[];
  if(v===`local`){
    let mapById=new Map(F.map(e=>[e.id,e]));
    for(let pid of pIds){let conv=mapById.get(pid);conv&&localPinned.push(conv)}
    let rawUnpinned=[];
    for(let conv of F){pSet.has(conv.id)||rawUnpinned.push(conv)}
    localUnpinned=j?rawUnpinned:_sortByRecentOrder(rawUnpinned,x=>x.id,recOrd);
  }
  let allLocalUnpinnedIds=localUnpinned.map(x=>x.id),
      visibleLocalUnpinned=localUnpinned.slice(0,recentLimit),
      hiddenLocalCount=Math.max(0,localUnpinned.length-visibleLocalUnpinned.length);
  let H=v===`local`&&(F.length?(0,Z.jsxs)(Z.Fragment,{children:[
    localPinned.length>0&&(0,Z.jsxs)(`div`,{className:`mb-0.5`,children:[
      (0,Z.jsxs)(`button`,{type:`button`,onClick:()=>setPCollapsed(!pCollapsed),className:`flex w-full items-center justify-between px-[var(--padding-row-x)] py-0.5 text-xs font-medium text-tertiary hover:text-default`,children:[
        (0,Z.jsxs)(`span`,{className:`flex items-center gap-1`,children:[(0,Z.jsx)(_PinSvg,{filled:!0,className:`size-3 text-[var(--color-text-info,#3b82f6)]`}),`置顶会话 (${localPinned.length})`]}),
        (0,Z.jsx)(`span`,{children:pCollapsed?`▸`:`▾`})
      ]}),
      !pCollapsed&&localPinned.map(e=>(0,Z.jsx)(_DraggableRow,{dndId:e.id,dndGroup:`pinned`,onDropReorder:info=>onDndDrop({...info,allUnpinnedIds:allLocalUnpinnedIds}),children:(0,Z.jsx)(An,{conversationId:e.id,hostId:e.hostId,updatedAt:e.recencyAt??e.updatedAt,isActive:y===e.id,isPinned:!0,onTogglePin:()=>tPin(e.id,!1),onClose:i,onActiveArchiveStart:m})},`pin-${e.id}`)),
      (0,Z.jsx)(`div`,{className:`mx-2 my-1 border-t-[0.5px] border-default opacity-50`})
    ]}),
    localUnpinned.length>0&&(0,Z.jsxs)(`div`,{children:[
      (0,Z.jsxs)(`div`,{className:`flex w-full items-center justify-between px-[var(--padding-row-x)] py-0.5 text-xs font-medium text-tertiary`,children:[
        (0,Z.jsxs)(`button`,{type:`button`,onClick:()=>setRCollapsed(!rCollapsed),className:`flex items-center gap-1 hover:text-default`,children:[
          (0,Z.jsx)(`span`,{children:`历史会话 (${visibleLocalUnpinned.length}/${localUnpinned.length})`}),
          (0,Z.jsx)(`span`,{children:rCollapsed?`▸`:`▾`})
        ]}),
        recOrd.length>0&&(0,Z.jsx)(`button`,{type:`button`,onClick:resetRecentOrder,className:`text-[10px] opacity-60 hover:opacity-100 hover:text-default`,title:`恢复按时间默认排序`,children:`重置排序`})
      ]}),
      !rCollapsed&&visibleLocalUnpinned.map(e=>(0,Z.jsx)(_DraggableRow,{dndId:e.id,dndGroup:`recent`,onDropReorder:info=>onDndDrop({...info,allUnpinnedIds:allLocalUnpinnedIds}),children:(0,Z.jsx)(An,{conversationId:e.id,hostId:e.hostId,updatedAt:e.recencyAt??e.updatedAt,isActive:y===e.id,isPinned:!1,onTogglePin:()=>tPin(e.id,!0),onClose:i,onActiveArchiveStart:m})},e.id)),
      !rCollapsed&&!j&&localUnpinned.length>_RECENT_DEFAULT_LIMIT&&(0,Z.jsx)(`button`,{
        type:`button`,
        onClick:()=>setShowAllRecent(!showAllRecent),
        className:`w-full px-[var(--padding-row-x)] py-1 text-start text-xs text-tertiary opacity-70 hover:opacity-100`,
        children:showAllRecent?`收起至最近 ${_RECENT_DEFAULT_LIMIT} 条`:`展开更多 (${hiddenLocalCount} 条)...`
      })
    ]})
  ]}):j?(0,Z.jsx)(dn,{}):(0,Z.jsx)(Kt,{}));

  let recentPinned=[],recentUnpinned=[];
  if(v===`recent`){
    let mapById=new Map;
    for(let item of I){let tid=_itemThreadId(item);tid&&mapById.set(tid,item)}
    for(let pid of pIds){let item=mapById.get(pid);item&&recentPinned.push(item)}
    let rawUnpinned=[];
    for(let item of I){let tid=_itemThreadId(item);(!tid||!pSet.has(tid))&&rawUnpinned.push(item)}
    recentUnpinned=j?rawUnpinned:_sortByRecentOrder(rawUnpinned,_itemThreadId,recOrd);
  }
  let allRecentUnpinnedIds=recentUnpinned.map(_itemThreadId).filter(Boolean),
      visibleRecentUnpinned=recentUnpinned.slice(0,recentLimit),
      hiddenRecentCount=Math.max(0,recentUnpinned.length-visibleRecentUnpinned.length);
  let U=v===`recent`&&(n.isError&&D.length===0?(0,Z.jsx)(Dn,{onRetry:()=>n.refetch()}):n.isLoading&&D.length===0?(0,Z.jsx)(En,{}):I.length===0?j?(0,Z.jsx)(dn,{}):(0,Z.jsx)(Kt,{}):(0,Z.jsxs)(Z.Fragment,{children:[
    n.isError&&(0,Z.jsxs)(`div`,{className:`mx-1 my-1 flex items-center justify-between gap-2 px-1 text-base text-default`,children:[(0,Z.jsx)(x,{id:`codex.recentTasksMenu.errorCloud.inline`,defaultMessage:`Failed to load cloud chats.`}),(0,Z.jsx)(J,{size:`default`,color:`outline`,onClick:()=>n.refetch(),children:(0,Z.jsx)(x,{id:`codex.common.retry`,defaultMessage:`Retry`})})]}),
    n.isPending&&!D.length&&(0,Z.jsx)(`div`,{className:`mx-1 my-1 flex items-center gap-2 text-sm text-tertiary`,children:(0,Z.jsx)(gt,{className:`icon-xs`})}),
    recentPinned.length>0&&(0,Z.jsxs)(`div`,{className:`mb-0.5`,children:[
      (0,Z.jsxs)(`button`,{type:`button`,onClick:()=>setPCollapsed(!pCollapsed),className:`flex w-full items-center justify-between px-[var(--padding-row-x)] py-0.5 text-xs font-medium text-tertiary hover:text-default`,children:[
        (0,Z.jsxs)(`span`,{className:`flex items-center gap-1`,children:[(0,Z.jsx)(_PinSvg,{filled:!0,className:`size-3 text-[var(--color-text-info,#3b82f6)]`}),`置顶会话 (${recentPinned.length})`]}),
        (0,Z.jsx)(`span`,{children:pCollapsed?`▸`:`▾`})
      ]}),
      !pCollapsed&&recentPinned.map(e=>{
        let tid=_itemThreadId(e);
        return(0,Z.jsx)(_DraggableRow,{dndId:tid,dndGroup:`pinned`,onDropReorder:info=>onDndDrop({...info,allUnpinnedIds:allRecentUnpinnedIds}),children:(0,Z.jsx)(jn,{item:e,isActive:e.kind===`local`&&e.conversation!=null&&y===e.conversation.id,isPinned:!0,onTogglePin:()=>{tid&&tPin(tid,!1)},onClose:i,onActiveArchiveStart:m})},`pin-${e.key}`);
      }),
      (0,Z.jsx)(`div`,{className:`mx-2 my-1 border-t-[0.5px] border-default opacity-50`})
    ]}),
    recentUnpinned.length>0&&(0,Z.jsxs)(`div`,{children:[
      (0,Z.jsxs)(`div`,{className:`flex w-full items-center justify-between px-[var(--padding-row-x)] py-0.5 text-xs font-medium text-tertiary`,children:[
        (0,Z.jsxs)(`button`,{type:`button`,onClick:()=>setRCollapsed(!rCollapsed),className:`flex items-center gap-1 hover:text-default`,children:[
          (0,Z.jsx)(`span`,{children:`历史会话 (${visibleRecentUnpinned.length}/${recentUnpinned.length})`}),
          (0,Z.jsx)(`span`,{children:rCollapsed?`▸`:`▾`})
        ]}),
        recOrd.length>0&&(0,Z.jsx)(`button`,{type:`button`,onClick:resetRecentOrder,className:`text-[10px] opacity-60 hover:opacity-100 hover:text-default`,title:`恢复按时间默认排序`,children:`重置排序`})
      ]}),
      !rCollapsed&&visibleRecentUnpinned.map(e=>{
        let tid=_itemThreadId(e);
        return(0,Z.jsx)(_DraggableRow,{dndId:tid,dndGroup:`recent`,onDropReorder:info=>onDndDrop({...info,allUnpinnedIds:allRecentUnpinnedIds}),children:(0,Z.jsx)(jn,{item:e,isActive:e.kind===`local`&&e.conversation!=null&&y===e.conversation.id,isPinned:!1,onTogglePin:()=>{tid&&tPin(tid,!0)},onClose:i,onActiveArchiveStart:m})},e.key);
      }),
      !rCollapsed&&!j&&recentUnpinned.length>_RECENT_DEFAULT_LIMIT&&(0,Z.jsx)(`button`,{
        type:`button`,
        onClick:()=>setShowAllRecent(!showAllRecent),
        className:`w-full px-[var(--padding-row-x)] py-1 text-start text-xs text-tertiary opacity-70 hover:opacity-100`,
        children:showAllRecent?`收起至最近 ${_RECENT_DEFAULT_LIMIT} 条`:`展开更多 (${hiddenRecentCount} 条)...`
      })
    ]})
  ]}));

  let W=(0,Z.jsxs)(te.Section,{className:isSb?`vertical-scroll-fade-mask flex min-h-0 flex-1 flex-col gap-0 overflow-y-auto pb-2`:`vertical-scroll-fade-mask flex max-h-[220px] flex-col gap-0 overflow-y-auto pb-1`,children:[B,H,U]});
  return(0,Z.jsxs)(`div`,{className:isSb?`flex min-h-0 flex-1 w-full flex-col gap-1 px-1`:`flex max-h-[280px] w-[calc(var(--radix-popper-available-width)_-_var(--padding-panel))] flex-col gap-1`,children:[L,R,z,W]});
}
function wn(e){return e.kind===`remote`}
function Tn(e,t){let n=e.label?.trim();return n&&n.length>0?n:e.phase===`failed`?t.formatMessage({id:`recentTasks.worktreeInitFailedTitle`,defaultMessage:`Worktree init failed`}):t.formatMessage({id:`recentTasks.worktreeSettingUpTitle`,defaultMessage:`Setting up worktree`})}
function En(){return(0,Z.jsx)(`div`,{className:`flex h-48 items-center justify-center gap-2 text-sm text-tertiary`,children:(0,Z.jsx)(gt,{className:`icon-xs`})})}
function Dn(e){let{onRetry:n}=e;return(0,Z.jsxs)(`div`,{className:`flex h-48 items-center justify-center gap-3 text-sm text-tertiary`,children:[(0,Z.jsx)(x,{id:`codex.recentTasksMenu.errorCloud`,defaultMessage:`Failed to load chats.`}),(0,Z.jsx)(J,{size:`default`,color:`outline`,onClick:n,children:(0,Z.jsx)(x,{id:`codex.common.retry`,defaultMessage:`Retry`})})]})}
var On,kn,Z,An,jn,Mn=e((()=>{
  On=C(),y(),kn=t(v(),1),p(),_(),yt(),ot(),Be(),Le(),nt(),ze(),ce(),De(),je(),D(),M(),Me(),pe(),A(),L(),Vt(),Gt(),Yt(),nn(),un(),mn(),gn(),Sn(),O(),Z=r(),
  An=(0,kn.memo)(function(e){
    let{conversationId:n,hostId:r,updatedAt:i,isActive:a,isPinned:isPin,onTogglePin:tPin,onClose:o,onActiveArchiveStart:s}=e,
        c=i==null?void 0:(0,Z.jsx)(ht,{dateString:new Date(i).toISOString()});
    return(0,Z.jsx)(Te,{
      conversationId:n,
      hostId:r,
      isActive:a,
      metaContent:c,
      onClick:o,
      onActiveArchiveStart:s,
      titlePrefix:isPin?(0,Z.jsx)(_PinSvg,{filled:!0,className:`size-3 shrink-0 text-[var(--color-text-info,#3b82f6)]`}):void 0,
      additionalHoverActionCount:1,
      renderActions:tPin?({archive:arc,requestArchive:reqArc})=>(0,Z.jsx)(_RowHoverActions,{isPinned:!!isPin,onTogglePin:tPin,onArchive:reqArc??arc}):void 0
    });
  }),
  jn=(0,kn.memo)(function(e){
    let{item:n,isActive:r,isPinned:isPin,onTogglePin:tPin,onClose:i,onActiveArchiveStart:a}=e,o=l(Pe),{cancelPendingWorktree:s}=ie();
    switch(n.kind){
      case`remote`:return(0,Z.jsx)(N,{task:n.task,onClose:i});
      case`local`:{
        if(n.conversation==null){
          return(0,Z.jsx)(B,{task:n.pendingWorktree,hasAttention:n.pendingWorktree.needsAttention,onClick:()=>{H(o,n.pendingWorktree),i()},onArchive:()=>{s(n.pendingWorktree.id)}});
        }
        let dt=n.conversation.recencyAt??n.conversation.updatedAt,
            c=dt==null?void 0:(0,Z.jsx)(ht,{dateString:new Date(dt).toISOString()});
        return(0,Z.jsx)(Te,{
          conversationId:n.conversation.id,
          hostId:n.conversation.hostId,
          isActive:r,
          metaContent:c,
          onClick:i,
          onActiveArchiveStart:a,
          titlePrefix:isPin?(0,Z.jsx)(_PinSvg,{filled:!0,className:`size-3 shrink-0 text-[var(--color-text-info,#3b82f6)]`}):void 0,
          additionalHoverActionCount:1,
          renderActions:tPin?({archive:arc,requestArchive:reqArc})=>(0,Z.jsx)(_RowHoverActions,{isPinned:!!isPin,onTogglePin:tPin,onArchive:reqArc??arc}):void 0
        });
      }
    }
  })
}));
"""
    txt = txt[:idx3] + new_cn_block + txt[idx4:]

    # 5. Add _FontSizeControl, _CurrentChatPinBtn, _SidebarHeaderControl before Bn(e)
    idx_bn = txt.find("function Bn(e){")
    if idx_bn == -1:
        sys.exit(f"[ERROR] Could not locate `function Bn(e)` in {hdr_js.name}")

    sidebar_components = """function _FontSizeControl(){
  let[sz,setSz]=(0,kn.useState)(()=>_readFontSize());
  (0,kn.useEffect)(()=>{
    _applyFontSizeCss(sz);
    let onUpdate=e=>setSz(_readFontSize()),
        onKey=ev=>{
          if((ev.metaKey||ev.ctrlKey)&&!ev.altKey){
            if(ev.key===`-`||ev.key===`_`){ev.preventDefault(),ev.stopPropagation(),_writeFontSize(_readFontSize()-1)}
            else if(ev.key===`=`||ev.key===`+`){ev.preventDefault(),ev.stopPropagation(),_writeFontSize(_readFontSize()+1)}
            else if(ev.key===`0`){ev.preventDefault(),ev.stopPropagation(),_writeFontSize(_DEFAULT_FONT_SIZE)}
          }
        };
    return window.addEventListener(`codex-cursor-fontsize-updated`,onUpdate),window.addEventListener(`keydown`,onKey,!0),()=>{
      window.removeEventListener(`codex-cursor-fontsize-updated`,onUpdate),window.removeEventListener(`keydown`,onKey,!0);
    };
  },[]);
  return(0,$.jsxs)(`div`,{
    className:`flex items-center rounded-md border border-default/40 px-0.5 text-[11px] text-tertiary select-none`,
    title:`调节 Codex 字体大小 (⌘- 缩小 / ⌘= 放大 / 点击数字恢复 13px)`,
    children:[
      (0,$.jsx)(`button`,{
        type:`button`,
        onClick:e=>{e.stopPropagation(),_writeFontSize(sz-1)},
        className:`px-1 py-0.5 hover:text-default cursor-interaction`,
        title:`缩小字体 (⌘-)`,
        children:`A-`
      }),
      (0,$.jsx)(`button`,{
        type:`button`,
        onClick:e=>{e.stopPropagation(),_writeFontSize(_DEFAULT_FONT_SIZE)},
        className:`px-0.5 py-0.5 font-mono text-[10px] opacity-80 hover:opacity-100 hover:text-default cursor-interaction`,
        title:`点击恢复默认字号 (${_DEFAULT_FONT_SIZE}px)`,
        children:`${sz}`
      }),
      (0,$.jsx)(`button`,{
        type:`button`,
        onClick:e=>{e.stopPropagation(),_writeFontSize(sz+1)},
        className:`px-1 py-0.5 hover:text-default cursor-interaction`,
        title:`放大字体 (⌘=)`,
        children:`A+`
      })
    ]
  });
}
function _CurrentChatPinBtn(){
  let cid=a(`/local/:conversationId`)?.params?.conversationId??null,
      {pinnedSet:pSet,togglePin:tPin}=_usePinnedThreads();
  if(!cid)return null;
  let isPin=pSet.has(cid),label=isPin?`取消置顶当前会话`:`置顶当前会话`;
  return(0,$.jsx)(lt,{
    tooltipContent:label,
    children:(0,$.jsx)(J,{
      color:isPin?`ghostActive`:`ghost`,
      size:`icon`,
      "aria-label":label,
      onClick:e=>{e.preventDefault(),e.stopPropagation(),tPin(cid,!isPin)},
      className:isPin?`text-[var(--color-text-info,#3b82f6)]`:`opacity-75 hover:opacity-100`,
      children:(0,$.jsx)(_PinSvg,{filled:isPin,className:`size-3.5`})
    })
  });
}
var _SIDEBAR_WIDTH_KEY=`codex.cursor.sidebarWidth`,_DEFAULT_SB_WIDTH=240;
function _readSidebarWidth(){try{let v=Number(localStorage.getItem(_SIDEBAR_WIDTH_KEY));return Number.isFinite(v)&&v>=150&&v<=560?Math.round(v):_DEFAULT_SB_WIDTH}catch{return _DEFAULT_SB_WIDTH}}
function _SidebarHeaderControl(e){
  let{cloudtasksQuery:v,localConversations:y}=e,
      newChatNav=ve(),
      [open,setOpen]=(0,kn.useState)(()=>{try{return localStorage.getItem(_SIDEBAR_OPEN_KEY)===`true`}catch{return!1}}),
      [docked,setDocked]=(0,kn.useState)(()=>{try{return localStorage.getItem(_SIDEBAR_DOCK_KEY)!==`false`}catch{return!0}}),
      [customW,setCustomW]=(0,kn.useState)(()=>_readSidebarWidth()),
      [resizing,setResizing]=(0,kn.useState)(!1),
      [winW,setWinW]=(0,kn.useState)(()=>typeof window<`u`?window.innerWidth:800),
      maxAllowedW=Math.max(180,Math.min(520,Math.floor(winW*0.65))),
      sbWidth=Math.max(150,Math.min(customW,maxAllowedW)),
      canDock=winW>=420,
      effectiveDocked=open&&docked&&canDock;
  (0,kn.useEffect)(()=>{
    let onToggle=()=>setOpen(prev=>{let next=!prev;try{localStorage.setItem(_SIDEBAR_OPEN_KEY,String(next))}catch{}return next}),
        onResize=()=>setWinW(window.innerWidth),
        onWidthSync=ev=>{if(typeof ev.detail==`number`)setCustomW(ev.detail)},
        onKey=ev=>{
          if((ev.metaKey||ev.ctrlKey)&&!ev.altKey&&(ev.key.toLowerCase()===`b`&&!ev.shiftKey||ev.key.toLowerCase()===`s`&&ev.shiftKey)){
            ev.preventDefault(),ev.stopPropagation(),onToggle();
          }
        };
    return window.addEventListener(`toggle-codex-cursor-sidebar`,onToggle),window.addEventListener(`resize`,onResize),window.addEventListener(`codex-cursor-sbwidth-updated`,onWidthSync),window.addEventListener(`keydown`,onKey,!0),()=>{
      window.removeEventListener(`toggle-codex-cursor-sidebar`,onToggle),window.removeEventListener(`resize`,onResize),window.removeEventListener(`codex-cursor-sbwidth-updated`,onWidthSync),window.removeEventListener(`keydown`,onKey,!0);
    };
  },[]);
  (0,kn.useEffect)(()=>{
    let root=document.getElementById(`root`);
    if(!root)return;
    if(effectiveDocked){
      root.style.paddingLeft=`${sbWidth}px`;
      root.style.boxSizing=`border-box`;
      root.style.transition=resizing?`none`:`padding-left 140ms ease`;
    }else{
      root.style.paddingLeft=``;
    }
    return()=>{root.style.paddingLeft=``};
  },[effectiveDocked,sbWidth,resizing]);
  let toggleOpen=()=>{
    let next=!open;
    setOpen(next);
    try{localStorage.setItem(_SIDEBAR_OPEN_KEY,String(next))}catch{}
  };
  let toggleDocked=()=>{
    let next=!docked;
    setDocked(next);
    try{localStorage.setItem(_SIDEBAR_DOCK_KEY,String(next))}catch{}
  };
  let saveWidth=w=>{
    let clamped=Math.max(150,Math.min(520,Math.round(w)));
    setCustomW(clamped);
    try{localStorage.setItem(_SIDEBAR_WIDTH_KEY,String(clamped))}catch{}
    window.dispatchEvent(new CustomEvent(`codex-cursor-sbwidth-updated`,{detail:clamped}));
  };
  let startResize=ev=>{
    if(ev.button!==0)return;
    ev.preventDefault(),ev.stopPropagation();
    setResizing(!0);
    let maxW=Math.max(180,Math.min(520,Math.floor(window.innerWidth*0.75)));
    let onMove=mev=>{
      mev.preventDefault();
      let nextW=Math.max(150,Math.min(maxW,Math.round(mev.clientX)));
      setCustomW(nextW);
    };
    let onUp=uev=>{
      window.removeEventListener(`pointermove`,onMove,!0);
      window.removeEventListener(`pointerup`,onUp,!0);
      window.removeEventListener(`pointercancel`,onUp,!0);
      setResizing(!1);
      let finalW=Math.max(150,Math.min(maxW,Math.round(uev.clientX)));
      saveWidth(finalW);
    };
    window.addEventListener(`pointermove`,onMove,!0);
    window.addEventListener(`pointerup`,onUp,!0);
    window.addEventListener(`pointercancel`,onUp,!0);
  };
  let portalNode=open&&typeof document<`u`&&_ReactDOM?.createPortal?_ReactDOM.createPortal(
    (0,$.jsxs)($.Fragment,{children:[
      !effectiveDocked&&(0,$.jsx)(`div`,{
        onClick:toggleOpen,
        style:{position:`fixed`,inset:0,left:`${sbWidth}px`,zIndex:48,backgroundColor:`rgba(0,0,0,0.28)`}
      }),
      (0,$.jsxs)(`aside`,{
        "aria-label":`Codex Session Sidebar`,
        style:{
          position:`fixed`,
          top:0,
          left:0,
          bottom:0,
          width:`${sbWidth}px`,
          zIndex:49,
          display:`flex`,
          flexDirection:`column`,
          backgroundColor:`var(--vscode-sideBar-background, var(--color-background-surface, #1e1e1e))`,
          color:`var(--vscode-sideBar-foreground, var(--color-text-default, inherit))`,
          borderRight:resizing?`2px solid #3b82f6`:`1px solid var(--vscode-sideBarSectionHeader-border, rgba(128,128,128,0.22))`,
          boxShadow:effectiveDocked?`none`:`4px 0 16px rgba(0,0,0,0.35)`,
          userSelect:resizing?`none`:`auto`
        },
        children:[
          (0,$.jsxs)(`div`,{
            className:`flex items-center justify-between px-2.5 py-2 border-b border-default`,
            children:[
              (0,$.jsxs)(`div`,{className:`flex items-center gap-1.5 min-w-0`,children:[
                (0,$.jsx)(J,{color:`ghost`,size:`icon`,title:`收起会话侧栏 (⌘B)`,"aria-label":`Close sidebar`,onClick:toggleOpen,children:(0,$.jsx)(_SidebarSvg,{className:`size-4`})}),
                (0,$.jsx)(`span`,{className:`text-xs font-semibold truncate`,children:`会话列表 (${y?.length??0})`})
              ]}),
              (0,$.jsxs)(`div`,{className:`flex items-center gap-0.5 shrink-0`,children:[
                canDock&&(0,$.jsx)(J,{
                  color:docked?`ghostActive`:`ghost`,
                  size:`icon`,
                  title:docked?`当前：常驻分栏（点击切换为浮层抽屉）`:`当前：浮层抽屉（点击切换为常驻分栏）`,
                  onClick:toggleDocked,
                  className:`text-xs`,
                  children:(0,$.jsx)(`span`,{className:`text-[11px] font-medium px-1`,children:docked?`常驻`:`浮层`})
                }),
                (0,$.jsx)(J,{
                  color:`ghost`,
                  size:`icon`,
                  title:`新建会话 (New chat)`,
                  onClick:()=>{newChatNav(),!effectiveDocked&&toggleOpen()},
                  children:(0,$.jsx)(Xe,{"aria-hidden":!1,asset:d})
                })
              ]})
            ]
          }),
          (0,$.jsx)(Cn,{
            isSidebar:!0,
            cloudtasksQuery:v,
            localConversations:y??[],
            onClose:effectiveDocked?()=>{}:toggleOpen,
            autoFocusSearch:!1,
            showFilters:!0
          }),
          (0,$.jsx)(`div`,{
            onPointerDown:startResize,
            onDoubleClick:ev=>{ev.preventDefault(),ev.stopPropagation(),saveWidth(_DEFAULT_SB_WIDTH)},
            title:`左右拖动调整侧栏宽度（双击恢复默认 ${_DEFAULT_SB_WIDTH}px）`,
            style:{
              position:`absolute`,
              top:0,
              right:`-3px`,
              bottom:0,
              width:`6px`,
              cursor:`col-resize`,
              zIndex:55
            },
            className:`hover:bg-[#3b82f6]/60 transition-colors`
          })
        ]
      })
    ]}),
    document.body
  ):null;
  return(0,$.jsxs)(`div`,{className:`me-1 flex items-center`,children:[
    (0,$.jsx)(lt,{
      tooltipContent:open?`收起会话侧栏 (⌘B)`:`展开会话侧栏 (⌘B)`,
      children:(0,$.jsx)(J,{
        color:open?`ghostActive`:`ghost`,
        size:`icon`,
        "aria-label":`Toggle session sidebar`,
        onClick:toggleOpen,
        children:(0,$.jsx)(_SidebarSvg,{className:`size-4`})
      })
    }),
    portalNode
  ]});
}
"""
    txt = txt[:idx_bn] + sidebar_components + txt[idx_bn:]

    old_bn_t = "let T;t[31]!==s||t[32]!==!1?(T=null,t[31]=s,t[32]=!1,t[33]=T):T=t[33];"
    new_bn_t = "let T;t[31]!==v||t[32]!==y?(T=(0,$.jsx)(_SidebarHeaderControl,{cloudtasksQuery:v,localConversations:y}),t[31]=v,t[32]=y,t[33]=T):T=t[33];"
    txt = txt.replace(old_bn_t, new_bn_t, 1)

    old_bn_j = "children:[O,null,k,A]"
    new_bn_j = "children:[(0,$.jsx)(_FontSizeControl,{}),(0,$.jsx)(_CurrentChatPinBtn,{}),O,null,k,A]"
    txt = txt.replace(old_bn_j, new_bn_j, 1)

    old_qn = "zn(),Sn(),$=r(),"
    new_qn = "zn(),Sn(),_initPinnedThreads(),_initSidebarPin(),_ReactDOM=t(_reactDomMod(),1),$=r(),"
    txt = txt.replace(old_qn, new_qn, 1)

    hdr_js.write_text(txt, encoding="utf-8")
    return hdr_js


def check_syntax(files: list[Path]) -> None:
    node = shutil.which("node")
    if not node:
        return
    for f in files:
        if f.suffix == ".js":
            res = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
            if res.returncode != 0:
                sys.exit(f"[ERROR] JS syntax check failed on {f}:\n{res.stderr}")


def show_status(ext_dir: Path) -> None:
    assets_dir = ext_dir / "webview" / "assets"
    hdr_js = find_single_asset(assets_dir, "header-*.js")
    patched = MARKER in hdr_js.read_text(encoding="utf-8")
    print(f"Extension dir : {ext_dir}")
    print(f"Header asset  : {hdr_js.name}")
    print(f"Patch status  : {'PATCHED (active)' if patched else 'UNPATCHED'}")


def revert_all(ext_dir: Path) -> None:
    reverted = 0
    for suffix in [BACKUP_SUFFIX, LEGACY_BACKUP_SUFFIX]:
        for bak in ext_dir.rglob(f"*{suffix}"):
            orig = bak.with_name(bak.name[: -len(suffix)])
            shutil.copy2(bak, orig)
            reverted += 1
            print(f"[REVERTED] {orig.relative_to(ext_dir)}")
    if reverted == 0:
        print("[INFO] No backup files found to revert.")
    else:
        print("[DONE] Reverted successfully. Run `Developer: Reload Window` in Cursor.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch Cursor / VS Code OpenAI Codex extension.")
    parser.add_argument("--ext-dir", help="Path to openai.chatgpt-* extension directory")
    parser.add_argument("--status", action="store_true", help="Check whether the patch is active")
    parser.add_argument("--revert", action="store_true", help="Revert to original backup files")
    args = parser.parse_args()

    ext_dir = find_extension_dir(args.ext_dir)
    if args.status:
        show_status(ext_dir)
        return
    if args.revert:
        revert_all(ext_dir)
        return

    assets_dir = ext_dir / "webview" / "assets"
    patch_package_json(ext_dir)
    patch_extension_js(ext_dir)
    loc_js = patch_local_conversation_thread(assets_dir)
    patch_index_html(ext_dir)
    hdr_js = patch_header_js(assets_dir)
    check_syntax([ext_dir / "out" / "extension.js", loc_js, hdr_js])

    print(f"[SUCCESS] Patched Codex extension at: {ext_dir}")
    print("Please run `Developer: Reload Window` (Cmd/Ctrl + Shift + P) in Cursor to take effect.")


if __name__ == "__main__":
    main()
