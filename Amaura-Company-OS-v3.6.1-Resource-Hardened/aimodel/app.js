document.addEventListener("DOMContentLoaded", () => {
  const runBtn = document.getElementById("runBtn");
  const promptInput = document.getElementById("promptInput");
  const thinkingOutput = document.getElementById("thinkingOutput");
  const verificationOutput = document.getElementById("verificationOutput");

  const stepPlanning = document.getElementById("stepPlanning");
  const stepCoding = document.getElementById("stepCoding");
  const stepTesting = document.getElementById("stepTesting");
  const stepComplete = document.getElementById("stepComplete");

  runBtn.addEventListener("click", async () => {
    const prompt = promptInput.value.trim();
    if (!prompt) return alert("Please enter a task request.");

    runBtn.disabled = true;
    thinkingOutput.textContent = "Generating adaptive thinking trace...";
    verificationOutput.textContent = "Awaiting verification step...";

    stepPlanning.className = "step active";
    stepCoding.className = "step";
    stepTesting.className = "step";
    stepComplete.className = "step";

    try {
      stepCoding.className = "step active";
      const response = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt })
      });

      const data = await response.json();

      stepPlanning.className = "step done";
      stepCoding.className = "step done";
      stepTesting.className = "step active";

      thinkingOutput.textContent = data.thinking || "Plan generated successfully.";

      if (data.verification) {
        stepTesting.className = "step done";
        stepComplete.className = "step done";
        verificationOutput.textContent = `Status: ${data.verification.success ? 'SUCCESS' : 'FAILED'}\n` +
          `Attempts: ${data.verification.attempts}\n` +
          `Applied Files: ${(data.applied_files || []).join(', ')}\n\n` +
          `Logs:\n${data.verification.output || data.verification.error_log || 'All assertions passed cleanly.'}`;
      }
    } catch (err) {
      thinkingOutput.textContent = `Error: ${err.message}`;
    } finally {
      runBtn.disabled = false;
    }
  });
});
