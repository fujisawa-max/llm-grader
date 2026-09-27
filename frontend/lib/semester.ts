export const semesters: Record<string, string> = {first_semester:"前期", second_semester:"後期", spring:"春学期", fall:"秋学期", full_year:"通年", other:"その他"};
export const semesterLabel = (term: string, custom?: string | null) => custom && !Object.keys(semesters).includes(custom) ? custom : semesters[term] || "その他";
export const semesterOrder = (term: string) => Object.keys(semesters).indexOf(term);

