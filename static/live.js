// Shared by every page: keeps a live connection to /events and hands each new queue state to `onState`.
function subscribeToQueue(onState) {
  const status = document.getElementById("connection");
  const source = new EventSource("/events");

  source.onmessage = (event) => {
    if (status) status.hidden = true;
    onState(JSON.parse(event.data));
  };
  // EventSource reconnects by itself; just tell the user the numbers may be stale meanwhile.
  source.onerror = () => {
    if (status) status.hidden = false;
  };
}

// Estimated wait = average minutes per patient × number of people ahead.
function estimateMinutes(state, peopleAhead) {
  return state.minutes_per_patient * peopleAhead;
}

function formatWait(minutes) {
  if (minutes < 1) return "Any moment now";
  const rounded = Math.ceil(minutes);
  if (rounded < 60) return `About ${rounded} minute${rounded === 1 ? "" : "s"}`;
  const hours = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return `About ${hours} h ${rest} min`;
}

function formatServing(state) {
  return state.serving === null ? "—" : String(state.serving);
}
