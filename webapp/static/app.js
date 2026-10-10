const $ = (id) => document.getElementById(id);
let selected = null;
let lastQuery = null;
let page = 1;
let pollTimer = null;

async function api(path, options={}) {
  const response = await fetch(path, {headers: {'Content-Type':'application/json', ...(options.headers || {})}, ...options});
  const data = await response.json().catch(() => ({error:'The server returned an invalid response.'}));
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}

function showError(message) { const el=$('discover-error'); el.textContent=message; el.hidden=false; }
function clearError() { $('discover-error').hidden=true; }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function badgeClass(status) { return String(status || '').toLowerCase().replace(/[^a-z]/g,''); }

function renderCandidates(data) {
  $('result-count').textContent = data.group_total ? `${data.group_total} identity group${data.group_total === 1 ? '' : 's'} · ${data.total} records` : 'no matches';
  
  let bannerHtml = '';
  if (data.group_total === 1 && data.total > 1) {
    bannerHtml = `<div class="identity-summary-banner same-company">
      <span style="font-size: 18px;">✅</span>
      <div><strong>Identity check complete:</strong> All ${data.total} search records refer to the <strong>same company</strong>. We have verified and unified their corroborating sources below for your review.</div>
    </div>`;
  } else if (data.group_total > 1) {
    bannerHtml = `<div class="identity-summary-banner multiple-companies">
      <span style="font-size: 18px;">⚖️</span>
      <div><strong>Identity check complete:</strong> Detected ${data.group_total} distinct company entities across ${data.total} search records. Review the differences below before selecting.</div>
    </div>`;
  }

  $('coverage-note').textContent = data.error || `${data.coverage || 'Bounded public discovery'}${data.warnings?.length ? ' · ' + data.warnings.join(' ') : ''}`;
  const box=$('candidates');
  if (!data.candidates?.length) {
    box.className='candidates empty-state';
    box.innerHTML='<div class="empty-glyph">∅</div><strong>No verified candidate in the sources checked</strong><span>Try a spelling variation, broader keyword, country, city, or website.</span>';
  } else if (data.identity_groups?.length) {
    box.className='candidates';
    const groupsHtml = data.identity_groups.map(group => {
      const c = group.canonical_candidate;
      const linked = group.records.filter(r => r.candidate_id !== c.candidate_id);
      const isConfirmed = group.resolution === 'confirmed_same_company';
      const isPossible = group.resolution === 'possible_same_company';
      const badgeClass = isConfirmed ? 'badge-confirmed' : (isPossible ? 'badge-possible' : 'badge-distinct');
      const calloutClass = isConfirmed ? 'verified-callout' : (isPossible ? 'possible-callout' : 'distinct-callout');

      return `<article class="identity-group">
        <div class="group-top">
          <div>
            <span class="selected-label">IDENTITY RESOLUTION</span>
            <h3>${escapeHtml(c.legal_name)}</h3>
            <div class="candidate-meta">${escapeHtml(c.country)}${c.city ? ' · '+escapeHtml(c.city) : ''}${c.registration_number ? ' · '+escapeHtml(c.registration_number) : ''}${c.website ? ' · '+escapeHtml(c.website) : ''} · ${escapeHtml(c.status)}</div>
          </div>
          <span class="badge ${badgeClass}">${escapeHtml(group.resolution_label)}</span>
        </div>
        <p class="candidate-desc">${escapeHtml(c.description)}</p>
        <div class="group-reason ${calloutClass}"><strong>Why linked:</strong> ${escapeHtml(group.resolution_reason)}</div>
        ${linked.length ? `<details class="linked-records" ${isConfirmed ? 'open' : ''}><summary>Corroborating sources & linked records (${linked.length})</summary>${linked.map(r=>`<div class="linked-record"><strong>${escapeHtml(r.legal_name)}</strong><span>${escapeHtml(r.source_title)} · <a href="${escapeHtml(r.source_url)}" target="_blank" rel="noopener">${escapeHtml(r.website || r.source_url)}</a></span><small>${escapeHtml(r.match_strength)} · source: ${escapeHtml(r.provider)}</small></div>`).join('')}</details>` : ''}
        ${group.evidence_gaps?.length ? `<details class="linked-records"><summary>What is still missing</summary><ul>${group.evidence_gaps.map(g=>`<li>${escapeHtml(g)}</li>`).join('')}</ul></details>` : ''}
        <div class="group-bottom">
          <div class="candidate-source">↗ ${escapeHtml(c.source_title)} · ${escapeHtml(c.provider)} · verified ${escapeHtml(new Date(c.last_verified).toLocaleString())}</div>
          <button class="select-btn" data-id="${escapeHtml(c.candidate_id)}">Select verified profile</button>
        </div>
      </article>`;
    }).join('');

    box.innerHTML = bannerHtml + groupsHtml;
    box.querySelectorAll('.select-btn').forEach(btn => btn.addEventListener('click', () => {
      const candId = btn.dataset.id;
      const matchGroup = data.identity_groups?.find(g => g.canonical_candidate_id === candId || g.canonical_candidate?.candidate_id === candId);
      const foundCand = matchGroup ? matchGroup.canonical_candidate : data.candidates?.find(c => c.candidate_id === candId);
      if (foundCand) selectCandidate(foundCand);
    }));
  } else {
    box.className='candidates';
    box.innerHTML=data.candidates.map(c => `<article class="candidate">
      <div><h3>${escapeHtml(c.legal_name)}</h3>
      <div class="candidate-meta">${escapeHtml(c.country)}${c.city ? ' · '+escapeHtml(c.city) : ''}${c.registration_number ? ' · '+escapeHtml(c.registration_number) : ''} · ${escapeHtml(c.status)}</div>
      <p class="candidate-desc">${escapeHtml(c.description)}</p>
      <div class="candidate-source">↗ ${escapeHtml(c.source_title)} · ${escapeHtml(c.provider)} · verified ${escapeHtml(new Date(c.last_verified).toLocaleString())}</div>
      <p class="candidate-desc"><strong>Why this match:</strong> ${escapeHtml(c.match_explanation)}</p></div>
      <div><span class="badge ${badgeClass(c.match_strength)}">${escapeHtml(c.match_strength)}</span><br><button class="select-btn" data-id="${escapeHtml(c.candidate_id)}">Select entity</button></div>
    </article>`).join('');
    box.querySelectorAll('.select-btn').forEach(btn => btn.addEventListener('click', () => selectCandidate(data.candidates.find(c => c.candidate_id === btn.dataset.id))));
  }
  $('pagination').hidden=!(data.has_next || page>1);
  $('page-label').textContent=`Page ${page}`;
  $('prev-page').disabled=page<=1;
  $('next-page').disabled=!data.has_next;
}

async function discover(nextPage=1) {
  clearError(); page=nextPage;
  const payload={company:$('company').value.trim(),country:$('country').value.trim(),website:$('website').value.trim()||null,city:$('city').value.trim()||null,industry:$('industry').value.trim()||null,page,page_size:8};
  lastQuery=payload;
  $('candidates').className='candidates empty-state'; $('candidates').innerHTML='<div class="empty-glyph">…</div><strong>Searching public sources</strong><span>Keeping the search bounded and source-labelled.</span>';
  try { renderCandidates(await api('/api/discover',{method:'POST',body:JSON.stringify(payload)})); }
  catch (error) { showError(error.message); $('coverage-note').textContent='Discovery did not run.'; }
}

function selectCandidate(candidate) {
  selected=candidate; $('selected-name').textContent=candidate.legal_name; $('selected-detail').textContent=`${candidate.country}${candidate.city ? ' · '+candidate.city : ''} · ${candidate.match_strength} · ${candidate.source_title}`;
  $('research-section').hidden=false; $('research-section').scrollIntoView({behavior:'smooth',block:'start'});
  $('job-card').hidden=true;
}

async function startResearch(event) {
  event.preventDefault(); if(!selected) return;
  $('job-card').hidden=false; $('job-message').textContent='Submitting the selected entity to the existing research engine…';
  try { const job=await api('/api/research',{method:'POST',body:JSON.stringify({candidate_id:selected.candidate_id,options:{depth:$('depth').value,recent:$('recent').value,model:null}})}); renderJob(job); poll(job.job_id); }
  catch(error) { renderJob({status:'failed',stage:'validation',progress:100,message:error.message}); }
}

function renderJob(job) {
  $('job-state').textContent=job.status==='completed'?'Research ready':job.status==='partial'?'Research partial':job.status[0].toUpperCase()+job.status.slice(1);
  $('job-badge').textContent=job.status; $('job-badge').className='badge '+job.status; $('progress-bar').style.width=`${job.progress || 0}%`; $('job-stage').textContent=job.stage || 'working'; $('job-progress').textContent=`${job.progress || 0}%`; $('job-message').textContent=job.message || '';
}
async function poll(id) {
  clearTimeout(pollTimer);
  try { const job=await api(`/api/jobs/${id}`); renderJob(job); if(['queued','running'].includes(job.status)){pollTimer=setTimeout(()=>poll(id),1200)}else if(job.status==='completed'){loadArtifacts(id)} }
  catch(error){renderJob({status:'failed',stage:'connection',progress:100,message:error.message});}
}
async function loadArtifacts(id) {
  const data=await api(`/api/jobs/${id}/artifacts`);
  $('artifact-list').innerHTML=data.files.map(file=>{
    const isPdf = file.name.endsWith('.pdf');
    return `<a class="artifact-link ${isPdf?'pdf-badge':''}" download href="${file.url}">${isPdf ? '📄 ' : ''}${escapeHtml(file.name)} ↓</a>`;
  }).join('');
}
$('discover-form').addEventListener('submit', e=>{e.preventDefault();discover(1)});
$('research-form').addEventListener('submit', startResearch);
$('change-selection').addEventListener('click', ()=>{$('research-section').hidden=true;selected=null});
$('prev-page').addEventListener('click',()=>discover(page-1)); $('next-page').addEventListener('click',()=>discover(page+1));
api('/api/health').then(()=>{$('system-status').textContent='engine online'}).catch(()=>{$('system-status').textContent='local server unavailable'});
