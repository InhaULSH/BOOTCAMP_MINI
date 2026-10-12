/* New presentation only. Never transforms amounts, dates, scores or evidence. */
(() => {
  if (document.documentElement.dataset.uiVersion !== 'new') return;
  // New content is inserted by the existing renderer after its API request.
  const app=document.getElementById('app');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const animated=new WeakSet();
  const entryAnimations=new WeakMap();
  const motionSelector='#cloud text[role=button], .is-tile-map .sector-node:not([hidden])';
  let active=null,peers=[];
  const clearMotion=()=>{
    peers.forEach(node=>{node.style.removeProperty('--motion-x');node.style.removeProperty('--motion-y');node.style.removeProperty('--motion-scale');node.classList.remove('ui-selected');});
    peers=[];active=null;
  };
  const emphasize=node=>{
    if(active===node||reduced.matches)return;
    clearMotion();active=node;
    const surface=node.closest('svg')||node.parentElement;
    peers=[...surface.querySelectorAll(node.matches('.sector-node')?'.sector-node:not([hidden])':'text[role=button]')];
    peers.forEach(n=>entryAnimations.get(n)?.cancel());
    const bounds=(node.closest('svg')||node.closest('.sector-field')).getBoundingClientRect();
    const center=node.getBoundingClientRect(),cx=center.x+center.width/2,cy=center.y+center.height/2;
    peers.forEach(n=>{
      const r=n.getBoundingClientRect(),dx=r.x+r.width/2-cx,dy=r.y+r.height/2-cy,distance=Math.hypot(dx,dy);
      const scale=n===node?(node.matches('.sector-node')?1.015:1.025):1;
      const amount=n===node?0:Math.max(0,4-distance/140);
      let x=distance?dx/distance*amount:0,y=distance?dy/distance*amount:0;
      // Keep enlarged labels inside their viewport; never repack or change scores.
      const extraX=r.width*(scale-1)/2,extraY=r.height*(scale-1)/2;
      x=Math.min(bounds.right-r.right-extraX,Math.max(bounds.left-r.left+extraX,x));
      y=Math.min(bounds.bottom-r.bottom-extraY,Math.max(bounds.top-r.top+extraY,y));
      n.style.setProperty('--motion-x',x+'px');n.style.setProperty('--motion-y',y+'px');n.style.setProperty('--motion-scale',String(scale));
      if(n===node)n.classList.add('ui-selected');
    });
  };
  document.addEventListener('pointerover',event=>{const node=event.target.closest(motionSelector);if(node)emphasize(node);});
  document.addEventListener('pointerout',event=>{if(active&&event.target.closest(motionSelector)===active&&!active.contains(event.relatedTarget))clearMotion();});
  document.addEventListener('focusin',event=>{const node=event.target.closest(motionSelector);if(node)emphasize(node);});
  document.addEventListener('focusout',()=>clearMotion());
  reduced.addEventListener('change',()=>{clearMotion();});
  const animateEntries=()=>{
    if(reduced.matches||app.getAttribute('aria-busy')!=='false')return;
    app.querySelectorAll('#cloud svg,#sector-nodes').forEach(surface=>{
      const identity=surface.closest('#cloud')||surface;
      if(animated.has(identity))return;
      animated.add(identity);
      document.fonts.ready.then(()=>requestAnimationFrame(()=>{
        const items=[...identity.querySelectorAll(motionSelector)];
        items.forEach((node,i)=>{
          node.classList.add('ui-motion');
          if(reduced.matches||!node.isConnected)return;
          entryAnimations.set(node,node.animate([{opacity:.25,translate:`0 ${node.matches('.sector-node')?6:4}px`,scale:.985},{opacity:1,translate:'0 0',scale:1}],{duration:260,delay:Math.min(i*14,100),easing:'cubic-bezier(.22,1,.36,1)'}));
        });
      }));
    });
  };
  window.addEventListener('pageshow',event=>{
    if(event.persisted && app && !matchMedia('(prefers-reduced-motion: reduce)').matches)
      app.animate([{opacity:.8,transform:'translateY(6px)'},{opacity:1,transform:'translateY(0)'}],{duration:180,easing:'cubic-bezier(.22,1,.36,1)'});
  });
  const enhance=()=>{
    if(app.getAttribute('aria-busy')==='false'){app.classList.add('ui-page-ready');animateEntries();}
    app.querySelectorAll(motionSelector).forEach(node=>node.classList.add('ui-motion'));
    const cloud=document.getElementById('cloud');
    if(cloud && !cloud.parentElement.querySelector('.ui-cloud-help')) {
      cloud.previousElementSibling.textContent='키워드를 선택하면 용어 해설과 공시 내용을 볼 수 있어요.';
      const note=document.createElement('p');note.className='ui-cloud-help';
      note.textContent='🔥 최근 공시에서 언급이 늘어난 키워드입니다.';
      cloud.after(note);
    }
  };
  if(app){new MutationObserver(enhance).observe(app,{childList:true,subtree:true,attributes:true,attributeFilter:['aria-busy']});enhance();}
})();
