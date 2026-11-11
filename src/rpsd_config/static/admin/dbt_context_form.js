/* Documentary dbt fields use the same server-side validation as this display. */
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-dbt-context-type]").forEach((select) => {
        const form = select.form;
        if (!form || !select.dataset.dbtContextType) return;
        const update = () => {
            const documentary = select.value === select.dataset.dbtContextType;
            for (const [name, value] of Object.entries({options: "{}", result_contract: "structured_report", execution_reference: ""})) {
                const field = form.elements.namedItem(name);
                if (!field) continue;
                const row = field.closest(".form-row, .mb-3, p");
                if (row) row.hidden = documentary;
                if (documentary) field.value = value;
                field.disabled = documentary;
                if (name === "execution_reference" && row) {
                    const section = row.closest("fieldset");
                    if (section && section.querySelectorAll(".form-row").length === 1) section.hidden = documentary;
                }
            }
        };
        select.addEventListener("change", update);
        update();
    });
});
