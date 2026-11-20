for (const input of document.querySelectorAll('input[type="number"]')) {
  const stepper = document.createElement("span");
  stepper.className = "number-stepper";

  const label = input.labels?.[0]?.textContent.trim().replace(/:$/, "");
  const steps = Number(input.dataset.stepperSteps || 1);
  const decrease = createButton("−", "Giảm");
  const increase = createButton("+", "Tăng");

  input.before(stepper);
  stepper.append(decrease, input, increase);
  updateButtons();

  input.addEventListener("input", updateButtons);
  input.form?.addEventListener("reset", () => requestAnimationFrame(updateButtons));
  decrease.addEventListener("click", () => adjust(() => input.stepDown(steps)));
  increase.addEventListener("click", () => adjust(() => input.stepUp(steps)));

  function createButton(symbol, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = symbol;
    button.setAttribute("aria-label", label ? action + " " + label.toLowerCase() : action);
    return button;
  }

  function updateButtons() {
    const value = input.valueAsNumber;
    const locked = input.matches(":disabled, [readonly]") || input.validity.badInput;
    decrease.disabled = locked || (input.min !== "" && value <= Number(input.min));
    increase.disabled = locked || (input.max !== "" && value >= Number(input.max));
  }

  function adjust(step) {
    const previousValue = input.value;
    step();
    if (input.value !== previousValue) {
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
}
