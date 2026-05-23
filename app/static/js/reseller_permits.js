/**
 * Reseller permits — the "what businesses forget" page.
 *
 * Two views in one screen: an "Expiring within 30 days" alert strip on
 * top, and the full searchable list below. The expiring strip is the
 * thing nobody surfaces by default; this page makes it the first thing
 * an operator sees.
 *
 * Verification flow: each row has a "Verify on state lookup" button
 * that opens the official state's verification page in a new tab (URL
 * pre-filled when the state supports it). After the operator confirms
 * the permit is valid there, they click "Mark verified" here to stamp
 * `last_verified_at`. That's the manual two-step audit trail.
 */
const ResellerPermitsPage = {
    async render() {
        const [permits, customers, vendors, expiring] = await Promise.all([
            API.get('/reseller-permits'),
            API.get('/customers').catch(() => []),
            API.get('/vendors').catch(() => []),
            API.get('/reseller-permits/expiring?within_days=30'),
        ]);

        const custById = Object.fromEntries(customers.map(c => [c.id, c.name]));
        const vendById = Object.fromEntries(vendors.map(v => [v.id, v.name]));
        const nameFor = (p) => {
            if (p.entity_type === 'customer') return custById[p.entity_id] || `Customer ${p.entity_id}`;
            if (p.entity_type === 'vendor')   return vendById[p.entity_id] || `Vendor ${p.entity_id}`;
            return 'Company (own permit)';
        };

        const expiringStrip = expiring.length === 0 ? `
            <div class="card" style="padding:14px;background:#eaf5ec;border-left:4px solid #1f7a36;margin-bottom:16px">
                <strong>All clear.</strong> No active permits expire within 30 days.
            </div>` : `
            <div class="card" style="padding:14px;background:#fdecea;border-left:4px solid #a4242b;margin-bottom:16px">
                <strong>${expiring.length} permit${expiring.length === 1 ? '' : 's'} need attention</strong>
                — expires within 30 days or already expired:
                <ul style="margin:8px 0 0 18px;font-size:13px">
                    ${expiring.map(p => `
                        <li>
                            <strong>${escapeHtml(nameFor(p))}</strong>
                            (${escapeHtml(p.jurisdiction)} · ${escapeHtml(p.permit_number)}):
                            ${p.is_expired
                                ? `<span style="color:#a4242b">EXPIRED ${escapeHtml(String(Math.abs(p.days_to_expire)))} day${Math.abs(p.days_to_expire) === 1 ? '' : 's'} ago</span>`
                                : `expires in <strong>${p.days_to_expire}</strong> day${p.days_to_expire === 1 ? '' : 's'} (${escapeHtml(p.expires_at || '')})`}
                        </li>`).join('')}
                </ul>
            </div>`;

        const tableBody = permits.length === 0 ? `
            <tr><td colspan="8"><em>No reseller permits on file. Click "+ Add Permit" to record one.</em></td></tr>` :
            permits.map(p => {
                const status = p.is_expired
                    ? '<span style="color:#a4242b;font-weight:600">Expired</span>'
                    : (p.days_to_expire !== null && p.days_to_expire <= 30
                        ? '<span style="color:#a8761f;font-weight:600">Expires soon</span>'
                        : (p.is_active ? '<span style="color:#1f7a36">Active</span>' : '<span style="color:#888">Inactive</span>'));
                const verifiedText = p.last_verified_at
                    ? `<span title="${escapeHtml(p.verified_by || '')}">${p.last_verified_at.slice(0, 10)}</span>`
                    : '<span style="color:#a4242b">Never</span>';
                const verifyBtn = p.verification_url
                    ? `<a class="btn btn-sm btn-secondary" href="${escapeHtml(p.verification_url)}" target="_blank" rel="noopener">Open ${escapeHtml(p.jurisdiction)} lookup</a>`
                    : '';
                const businessName = ResellerPermitsPage._businessNameFor(p, custById, vendById);
                const taxId = ResellerPermitsPage._taxIdFor(p, customers, vendors);
                // Copy buttons: lets the operator paste the permit # + business
                // name + tax ID into the state form without manual retyping.
                const copyBtns = `
                    <button class="btn btn-sm btn-secondary" title="Copy permit #" onclick="ResellerPermitsPage._copy('${escapeHtml(p.permit_number)}', 'Permit #')">⧉ #</button>
                    <button class="btn btn-sm btn-secondary" title="Copy business name" onclick="ResellerPermitsPage._copy('${escapeHtml(businessName)}', 'Business name')">⧉ Name</button>
                    ${taxId ? `<button class="btn btn-sm btn-secondary" title="Copy tax ID / UBI" onclick="ResellerPermitsPage._copy('${escapeHtml(taxId)}', 'Tax ID')">⧉ Tax ID</button>` : ''}`;
                return `<tr>
                    <td>${escapeHtml(businessName)}</td>
                    <td>${escapeHtml(p.jurisdiction)}</td>
                    <td><code>${escapeHtml(p.permit_number)}</code></td>
                    <td>${p.expires_at ? escapeHtml(p.expires_at) : '<em>—</em>'}</td>
                    <td>${status}</td>
                    <td>${verifiedText}</td>
                    <td class="actions">
                        ${copyBtns}
                        ${verifyBtn}
                        <button class="btn btn-sm btn-primary" onclick="ResellerPermitsPage.markVerified(${p.id})">Mark verified</button>
                        <button class="btn btn-sm btn-secondary" onclick="ResellerPermitsPage.showForm(${p.id})">Edit</button>
                        <button class="btn btn-sm btn-danger" onclick="ResellerPermitsPage.del(${p.id})">Delete</button>
                    </td>
                </tr>`;
            }).join('');

        return `
            <div class="page-header">
                <h2>Reseller Permits</h2>
                <button class="btn btn-primary" onclick="ResellerPermitsPage.showForm()">+ Add Permit</button>
            </div>
            ${expiringStrip}
            <div class="table-container">
                <table>
                    <thead><tr>
                        <th>Held by</th>
                        <th>State</th>
                        <th>Permit #</th>
                        <th>Expires</th>
                        <th>Status</th>
                        <th>Last verified</th>
                        <th>Actions</th>
                    </tr></thead>
                    <tbody>${tableBody}</tbody>
                </table>
            </div>
            <p style="font-size:12px;color:#888;margin-top:12px">
                Reseller permit verification is manual — click "Open WA lookup" (or your state's lookup) to
                check the permit on the official state site, then click "Mark verified" here to record that you did.
                Most states have no public real-time API.
            </p>`;
    },

    async showForm(id = null) {
        const [customers, vendors, existing] = await Promise.all([
            API.get('/customers').catch(() => []),
            API.get('/vendors').catch(() => []),
            id ? API.get(`/reseller-permits/${id}`) : Promise.resolve(null),
        ]);
        const p = existing || {
            entity_type: 'customer',
            entity_id: customers[0]?.id || null,
            jurisdiction: 'WA',
            permit_number: '',
            issued_at: '',
            expires_at: '',
            notes: '',
            is_active: true,
        };
        const custOpts = customers.map(c => `<option value="${c.id}"${p.entity_id === c.id && p.entity_type === 'customer' ? ' selected' : ''}>${escapeHtml(c.name)}</option>`).join('');
        const vendOpts = vendors.map(v => `<option value="${v.id}"${p.entity_id === v.id && p.entity_type === 'vendor' ? ' selected' : ''}>${escapeHtml(v.name)}</option>`).join('');

        openModal(id ? 'Edit Reseller Permit' : 'Add Reseller Permit', `
            <form onsubmit="ResellerPermitsPage.save(event, ${id || 'null'})">
                <div class="form-grid">
                    <div class="form-group"><label>Held by</label>
                        <select name="entity_type" onchange="ResellerPermitsPage._swapEntityOptions(this.value)">
                            <option value="customer"${p.entity_type === 'customer' ? ' selected' : ''}>Customer</option>
                            <option value="vendor"${p.entity_type === 'vendor' ? ' selected' : ''}>Vendor</option>
                            <option value="company"${p.entity_type === 'company' ? ' selected' : ''}>Our company</option>
                        </select></div>
                    <div class="form-group"><label>Entity</label>
                        <select name="entity_id" id="permit-entity-id">
                            <optgroup label="Customers" id="permit-cust-group">${custOpts}</optgroup>
                            <optgroup label="Vendors" id="permit-vend-group" style="display:none">${vendOpts}</optgroup>
                        </select></div>
                </div>
                <div class="form-grid">
                    <div class="form-group"><label>State *</label>
                        <input name="jurisdiction" value="${escapeHtml(p.jurisdiction || 'WA')}" required maxlength="20"
                               style="text-transform:uppercase"
                               onkeyup="ResellerPermitsPage._checkFormat()"></div>
                    <div class="form-group"><label>Permit number *</label>
                        <input name="permit_number" value="${escapeHtml(p.permit_number || '')}" required maxlength="50"
                               onkeyup="ResellerPermitsPage._checkFormat()"></div>
                </div>
                <p id="permit-format-hint" style="font-size:12px;margin:-6px 0 8px 0;color:#888"></p>
                <div class="form-grid">
                    <div class="form-group"><label>Issued</label>
                        <input name="issued_at" type="date" value="${escapeHtml(p.issued_at || '')}"></div>
                    <div class="form-group"><label>Expires</label>
                        <input name="expires_at" type="date" value="${escapeHtml(p.expires_at || '')}"></div>
                </div>
                <div class="form-group"><label>Notes</label>
                    <textarea name="notes" rows="2">${escapeHtml(p.notes || '')}</textarea></div>
                <label style="display:flex;align-items:center;gap:6px;font-size:13px">
                    <input type="checkbox" name="is_active" ${p.is_active !== false ? 'checked' : ''}> Active
                </label>
                <div class="form-actions" style="margin-top:12px">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>`);

        // Initialize entity-id <select> visibility to match the currently
        // selected entity_type (covers the edit case).
        ResellerPermitsPage._swapEntityOptions(p.entity_type);
        // Initial format check so the hint reflects current values on open.
        ResellerPermitsPage._checkFormat();
    },

    _swapEntityOptions(entityType) {
        const sel = document.getElementById('permit-entity-id');
        const custGroup = document.getElementById('permit-cust-group');
        const vendGroup = document.getElementById('permit-vend-group');
        if (!sel) return;
        if (entityType === 'company') {
            sel.disabled = true;
            sel.value = '';
        } else {
            sel.disabled = false;
            if (custGroup) custGroup.style.display = entityType === 'customer' ? '' : 'none';
            if (vendGroup) vendGroup.style.display = entityType === 'vendor' ? '' : 'none';
        }
    },

    async save(e, id) {
        e.preventDefault();
        const f = e.target;
        const entity_type = f.entity_type.value;
        const body = {
            entity_type,
            entity_id: entity_type === 'company' ? null : (parseInt(f.entity_id.value, 10) || null),
            jurisdiction: f.jurisdiction.value.trim().toUpperCase(),
            permit_number: f.permit_number.value.trim(),
            issued_at: f.issued_at.value || null,
            expires_at: f.expires_at.value || null,
            notes: f.notes.value || null,
            is_active: f.is_active.checked,
        };
        try {
            if (id) await API.put(`/reseller-permits/${id}`, body);
            else    await API.post('/reseller-permits', body);
            toast(id ? 'Permit updated' : 'Permit added');
            closeModal();
            App.navigate('#/reseller-permits');
        } catch (err) { toast(err.message, 'error'); }
    },

    async markVerified(id) {
        const who = prompt('Verifier (your name or initials):', '');
        if (who === null) return;  // operator cancelled
        try {
            await API.post(`/reseller-permits/${id}/mark-verified`, { verified_by: who });
            toast('Marked verified');
            App.navigate('#/reseller-permits');
        } catch (err) { toast(err.message, 'error'); }
    },

    async del(id) {
        if (!confirm('Delete this permit record? The audit trail goes away too.')) return;
        try {
            await API.del(`/reseller-permits/${id}`);
            toast('Permit deleted');
            App.navigate('#/reseller-permits');
        } catch (err) { toast(err.message, 'error'); }
    },

    // ----------------------------------------------------------------------
    // Permit-format QA + paste-into-state-lookup helpers
    // ----------------------------------------------------------------------

    // Per-state hints + regex. WA's modern reseller permit number is a
    // 9-digit string (mirrors the UBI number it's tied to); the legacy
    // format included dashes, which we strip before matching. Other
    // states left unconstrained — operators can still add permits we
    // can't validate; we just don't claim format guarantees.
    _FORMAT: {
        WA: {
            // Strip non-digits, then require 9 digits.
            strip: s => (s || '').replace(/\D/g, ''),
            valid: s => /^\d{9}$/.test((s || '').replace(/\D/g, '')),
            hint: 'WA reseller permits are 9 digits (often grouped XXX-XXX-XXX), tied to the business UBI.',
        },
        CA: {
            strip: s => (s || '').replace(/\D/g, ''),
            valid: s => /^\d{9,12}$/.test((s || '').replace(/\D/g, '')),
            hint: 'CA seller\'s permits are 9–12 digits.',
        },
        TX: {
            strip: s => (s || '').replace(/\D/g, ''),
            valid: s => /^\d{11}$/.test((s || '').replace(/\D/g, '')),
            hint: 'TX sales-tax permits are 11 digits.',
        },
    },

    _businessNameFor(permit, custById, vendById) {
        if (permit.entity_type === 'customer') return custById[permit.entity_id] || `Customer ${permit.entity_id}`;
        if (permit.entity_type === 'vendor')   return vendById[permit.entity_id] || `Vendor ${permit.entity_id}`;
        return 'Company (own permit)';
    },

    _taxIdFor(permit, customers, vendors) {
        // Tax ID = UBI in WA, sales tax registration in other states.
        // Look up the customer/vendor and return their tax_id if any.
        if (permit.entity_type === 'customer') {
            const c = customers.find(x => x.id === permit.entity_id);
            return c?.tax_id || '';
        }
        if (permit.entity_type === 'vendor') {
            const v = vendors.find(x => x.id === permit.entity_id);
            return v?.tax_id || '';
        }
        return '';
    },

    async _copy(text, label) {
        try {
            await navigator.clipboard.writeText(text);
            toast(`${label} copied to clipboard`);
        } catch {
            // Older browsers / non-secure contexts. Fall back to a prompt
            // so the operator can manually copy.
            window.prompt(`${label} (copy with Ctrl+C):`, text);
        }
    },

    // Live format check fired from the form's onkeyup. Updates the hint
    // text below the permit field — green when valid, amber when the
    // state has a rule and the input doesn't match, gray when we have
    // no rule for the state.
    _checkFormat() {
        const juris = (document.querySelector('[name="jurisdiction"]')?.value || '').toUpperCase().trim();
        const value = document.querySelector('[name="permit_number"]')?.value || '';
        const hint = document.getElementById('permit-format-hint');
        if (!hint) return;
        const rule = ResellerPermitsPage._FORMAT[juris];
        if (!rule) {
            hint.textContent = `No format rule for ${juris || 'this state'} — verify on the state lookup page.`;
            hint.style.color = '#888';
            return;
        }
        const cleaned = rule.strip(value);
        if (rule.valid(value)) {
            hint.textContent = `✓ Format matches ${juris} (${rule.hint})`;
            hint.style.color = '#1f7a36';
        } else {
            hint.textContent = `⚠ ${juris}: ${rule.hint} (you have ${cleaned.length} digits)`;
            hint.style.color = '#a8761f';
        }
    },
};
