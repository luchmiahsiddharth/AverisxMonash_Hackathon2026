/* 
   SDOC DASHBOARD JAVASCRIPT
 */


/* 
   BACKEND CONNECTION

   GET  /api/emails?category=&status=
   GET  /api/emails/{email_id}
   POST /api/emails/{email_id}/review

   Local backend:
   http://localhost:8000

   Docker:
   http://localhost:8080
 */

const API_URL = "http://localhost:8000";


/* 
   DEMO DATA
 */

const DEMO_EMAILS = [

    {
        email_id: "email_004",
        subject: "Please verify SI vs BL for booking 8842",
        category: "BL_COMPARISON",
        status: "MISMATCH",
        has_defect: true,
        defect_fields: ["container_count"]
    },

    {
        email_id: "email_005",
        subject: "New shipping instruction — Penang to Mont-Ida",
        category: "SI_REQUEST",
        status: "OK"
    },

    {
        email_id: "email_006",
        subject: "Invoice #4471 — payment terms question",
        category: "INVOICE_QUERY",
        status: "OK"
    },

    {
        email_id: "email_007",
        subject: "Re: check attached documents, container mismatch?",
        category: "BL_COMPARISON",
        status: "NEEDS_REVIEW",
        review_reason: "unreadable"
    },

    {
        email_id: "email_008",
        subject: "WIN A FREE CRUISE — click now!!",
        category: "SPAM",
        status: "OK"
    }

];


/*
   VARIABLES
 */

let emails = [];

let selectedId = null;

let usingDemo = false;

let activeFilter = "all";
/* 
   INITIALISE DASHBOARD
*/

async function init() {

    try {

        const res = await fetch(
            `${API_URL}/api/emails`
        );

        if (!res.ok) {
            throw new Error(
                `Server responded ${res.status}`
            );
        }

        emails = await res.json();

    } catch (err) {

        console.warn(
            "Backend not reachable — showing demo data instead:",
            err.message
        );

        emails = DEMO_EMAILS;

        usingDemo = true;
    }


    renderStats();

    renderList(emails);
    const hero = emails.find(e => e.status === "MISMATCH") || emails[0];
    if (hero) {
        selectEmail(hero.email_id);
    }
}


/* 
   STATISTICS
 */

function renderStats() {

    const total = emails.length;

    const mismatches =
        emails.filter(
            e => e.status === "MISMATCH"
        ).length;

    const review =
        emails.filter(
            e => e.status === "NEEDS_REVIEW"
        ).length;


    document.getElementById("stats").innerHTML =

        `<strong>${total}</strong> emails &nbsp;·&nbsp; ` +

        `<strong>${mismatches}</strong> mismatches &nbsp;·&nbsp; ` +

        `<strong>${review}</strong> need review` +

        (
            usingDemo
                ? ` &nbsp;·&nbsp; <span style="color:#ff667d">demo data</span>`
                : ""
        );
}


/* =========================================================
   RENDER EMAIL LIST
========================================================= */

function renderList(list) {

    const container =
        document.getElementById("email-list");


    if (list.length === 0) {

        container.innerHTML = `

            <div class="empty-state">

                <strong>
                    No emails match this search
                </strong>

                Try a different keyword.

            </div>

        `;

        return;
    }


    container.innerHTML = list.map(e => `

        <div
            class="email-row ${e.email_id === selectedId ? "active" : ""}"
            data-id="${e.email_id}"
        >

            <div class="subject">
                ${escapeHtml(
                    e.subject || "(no subject)"
                )}
            </div>


            <div class="meta">

                <span class="badge ${e.category}">
                    ${e.category}
                </span>


                <span class="status-pill ${e.status}">
                    ${(e.status || "UNKNOWN")
                        .replace("_", " ")}
                </span>


                <span class="id">
                    ${e.email_id}
                </span>

            </div>

        </div>

    `).join("");


    container
        .querySelectorAll(".email-row")
        .forEach(el => {

            el.addEventListener(
                "click",
                () => selectEmail(el.dataset.id)
            );

        });
}


/* =========================================================
   SELECT EMAIL
========================================================= */

async function selectEmail(id) {

    selectedId = id;

    renderList(
        currentFilteredList()
    );


    const detail =
        document.getElementById("detail");


    detail.innerHTML = `

        <div class="loading-state">
            Loading...
        </div>

    `;


    let email;

    let result;


    try {

        const res = await fetch(
            `${API_URL}/api/emails/${id}`
        );


        if (!res.ok) {

            throw new Error(
                `Server responded ${res.status}`
            );

        }


        const data = await res.json();


        email = data.email;

        result = data.result;


    } catch (err) {

        const demo =
            DEMO_EMAILS.find(
                e => e.email_id === id
            );


        email = {

            email_id: id,

            subject: demo?.subject,

            body:
                "(Not connected to backend — showing limited demo detail.)",

            attachments: []

        };


        result =
            demo || {
                status: "unknown",
                category: "GENERAL"
            };
    }


    /* =====================================================
       EMAIL CONTENT
    ===================================================== */

    let html = `

        <div class="card">

            <h2>
                ${escapeHtml(
                    email.subject || "(no subject)"
                )}
            </h2>


            <p class="sub">

                ${email.email_id}

                &nbsp;·&nbsp;

                ${escapeHtml(
                    (email.attachments || []).join(", ")
                    || "no attachments"
                )}

            </p>


            <p class="body-text">

                ${escapeHtml(
                    email.body || ""
                )}

            </p>

        </div>

    `;


    /* =====================================================
       CLASSIFICATION
    ===================================================== */

    html += `

        <div class="card">

            <h2>
                Classification
            </h2>

            <p>

                <span class="badge ${result.category}">
                    ${result.category}
                </span>

                &nbsp;

                status:

                <strong>
                    ${result.status}
                </strong>

                ${
                    result.review_reason
                        ? `
                            &nbsp;

                            reason:

                            <code>
                                ${escapeHtml(
                                    result.review_reason
                                )}
                            </code>
                          `
                        : ""
                }

            </p>

        </div>

    `;


    /* =====================================================
       MISMATCH
    ===================================================== */

    if (
        result.category === "BL_COMPARISON" &&
        result.status === "MISMATCH"
    ) {
        html += await renderMismatch(id, result.defect_fields || []);
    }


    /* =====================================================
       HUMAN REVIEW
    ===================================================== */

    if (
        result.status === "NEEDS_REVIEW"
    ) {

        html += `

            <div class="card review-panel">

                <h3>
                    This email needs human review
                </h3>


                <select id="correctedStatus">

                    <option value="OK">
                        Mark as OK
                    </option>

                    <option value="MISMATCH">
                        Mark as MISMATCH
                    </option>

                    <option value="NEEDS_REVIEW">
                        Still needs review
                    </option>

                </select>


                <textarea
                    id="reviewNotes"
                    placeholder="Notes (optional) — why you made this call"
                ></textarea>


                <button id="submitReviewBtn">
                    Submit review
                </button>


                <div
                    class="review-status"
                    id="reviewStatusMsg"
                ></div>

            </div>

        `;
    }


    detail.innerHTML = html;


    const btn =
        document.getElementById(
            "submitReviewBtn"
        );


    if (btn) {

        btn.addEventListener(
            "click",
            () => submitReview(id)
        );

    }
}


/* =========================================================
   MISMATCH TABLE
========================================================= */

async function renderMismatch(emailId, defectFields) {
    // Fetch the SI/BL field values from the backend
    let data;
    try {
        const res = await fetch(`${API_URL}/api/emails/${emailId}/fields`);
        data = await res.json();
    } catch (err) {
        return `<div class="card"><h2>Field comparison</h2>
            <p class="sub">Could not load field values.</p></div>`;
    }

    if (!data.si || !data.bl) {
        return `<div class="card"><h2>Field comparison</h2>
            <p class="sub">Attachments not available for this email.</p></div>`;
    }

    const FIELD_LABELS = {
        shipper: "Shipper",
        consignee: "Consignee",
        notify_party: "Notify Party",
        port_of_loading: "Port of Loading",
        port_of_discharge: "Port of Discharge",
        container_count: "Container Count",
        gross_weight_kg: "Gross Weight (kg)",
    };

    const rows = Object.keys(FIELD_LABELS).map(field => {
        const si = data.si[field] ?? "—";
        const bl = data.bl[field] ?? "—";
        const isDefect = defectFields.includes(field);
        return `
            <tr class="${isDefect ? "defect" : ""}">
                <td>${FIELD_LABELS[field]}</td>
                <td>${escapeHtml(String(si))}</td>
                <td>${escapeHtml(String(bl))}</td>
            </tr>
        `;
    }).join("");

    return `
        <div class="card">
            <h2>Field comparison</h2>
            <table class="fields-table">
                <thead>
                    <tr>
                        <th>Field</th>
                        <th>SI value</th>
                        <th>BL value</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}


/* =========================================================
   SUBMIT REVIEW
========================================================= */

async function submitReview(id) {

    const corrected_status =
        document.getElementById(
            "correctedStatus"
        ).value;


    const notes =
        document.getElementById(
            "reviewNotes"
        ).value;


    const msg =
        document.getElementById(
            "reviewStatusMsg"
        );


    const btn =
        document.getElementById(
            "submitReviewBtn"
        );


    btn.disabled = true;

    msg.textContent =
        "Submitting...";


    try {

        const res = await fetch(

            `${API_URL}/api/emails/${id}/review`,

            {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({

                    corrected_status,
                    notes

                })

            }

        );


        if (!res.ok) {

            throw new Error(
                `Server responded ${res.status}`
            );

        }


        msg.textContent =
            "Review saved.";


    } catch (err) {

        msg.textContent =
            `Could not save review (${err.message}) — is the backend running?`;

    } finally {

        btn.disabled = false;

    }
}


/* =========================================================
   SEARCH
========================================================= */

function currentFilteredList() {
    const q = document.getElementById("searchInput").value.toLowerCase();
    let list = emails;

    if (activeFilter === "BL_COMPARISON") {
        list = list.filter(e => e.category === "BL_COMPARISON");
    } else if (activeFilter === "NEEDS_REVIEW") {
        list = list.filter(e => e.status === "NEEDS_REVIEW");
    } else if (activeFilter === "MISMATCH") {
        list = list.filter(e => e.status === "MISMATCH");
    }

    if (!q) return list;

    return list.filter(e =>
        (e.subject || "").toLowerCase().includes(q) ||
        (e.category || "").toLowerCase().includes(q) ||
        (e.status || "").toLowerCase().includes(q)
    );
}


/* =========================================================
   SEARCH EVENT
========================================================= */

document
    .getElementById("searchInput")
    .addEventListener(
        "input",
        () => {

            renderList(
                currentFilteredList()
            );

        }
    );


document.querySelectorAll(".filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        activeFilter = btn.dataset.filter;
        renderList(currentFilteredList());
    });
});

/* =========================================================
   HTML ESCAPING
========================================================= */

function escapeHtml(s) {

    return String(s).replace(
        /[&<>"]/g,

        c => ({

            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;"

        }[c])
    );
}


/* =========================================================
   START APPLICATION
========================================================= */

init();