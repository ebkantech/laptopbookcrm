/* Client-side mirror of parties.kyc's format checks, for instant feedback.
 * The server re-checks everything; these only catch typing mistakes. */
const D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],
  [5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]];
const P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],
  [9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]];

export function verhoeffOk(digits) {
  let c = 0;
  [...digits].reverse().forEach((ch, i) => { c = D[c][P[i % 8][Number(ch)]]; });
  return c === 0;
}

export const ID_TYPES = [
  { id: "aadhaar", label: "Aadhaar", hint: "12 digits" },
  { id: "pan", label: "PAN", hint: "e.g. ABCDE1234F" },
  { id: "driving_licence", label: "Driving licence", hint: "e.g. DL0420110012345" },
  { id: "passport", label: "Passport", hint: "e.g. K1234567" },
  { id: "voter_id", label: "Voter ID", hint: "e.g. ABC1234567" },
  { id: "other", label: "Other ID", hint: "" },
];

/* "" when the number looks right, else what's wrong. */
export function idProblem(type, raw) {
  const v = String(raw || "").replace(/[\s-]/g, "").toUpperCase();
  if (!v) return "Enter the ID number.";
  switch (type) {
    case "aadhaar":
      if (!/^[2-9]\d{11}$/.test(v)) return "An Aadhaar number is 12 digits and doesn't start with 0 or 1.";
      return verhoeffOk(v) ? "" : "This isn't a valid Aadhaar number — check the digits.";
    case "pan":
      if (!/^[A-Z]{5}\d{4}[A-Z]$/.test(v)) return "A PAN is 5 letters, 4 digits, 1 letter.";
      return "PCHFATBLJG".includes(v[3]) ? "" : "The 4th character of this PAN isn't a valid holder type.";
    case "passport": return /^[A-Z]\d{7}$/.test(v) ? "" : "A passport number is 1 letter and 7 digits.";
    case "voter_id": return /^[A-Z]{3}\d{7}$/.test(v) ? "" : "A Voter ID is 3 letters and 7 digits.";
    case "driving_licence": return /^[A-Z]{2}\d{2}[A-Z0-9]{9,13}$/.test(v) ? "" : "Start with the state code and RTO number, e.g. DL0420110012345.";
    default: return /^[A-Z0-9/]{4,40}$/.test(v) ? "" : "Use letters and digits only.";
  }
}

export const KYC_LABEL = { verified: "ID verified", unverified: "ID not verified", none: "No ID on file" };
