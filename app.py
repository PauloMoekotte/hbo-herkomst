import streamlit as st
import pandas as pd
import plotly.express as px

# ---------------- BASISCONFIG ----------------
st.set_page_config(page_title="MBO-HBO studentenstromen (DUO)", layout="wide")

st.title("Dashboard MBO ↔ HBO studentenstromen (DUO-data)")

st.markdown(
    """
Upload een DUO-CSV met studentenstromen tussen mbo en hbo.
De app laat je kolommen uit de extract koppelen aan functionele labels,
controleert de data en biedt verschillende beleidsrelevante visualisaties en kengetallen.
"""
)

# ---------------- HULPFUNCTIES ----------------

def bereken_doorstroompercentage(df, mapping, group_labels=None):
    """
    Verwacht een mapping met o.a. 'aantal_studenten' en 'doorstroom_indicator'.
    Geeft percentage doorstromers binnen de groep terug.
    """
    col_aantal = mapping.get("aantal_studenten")
    col_ind = mapping.get("doorstroom_indicator")
    if not col_aantal or not col_ind:
        return None

    if col_aantal not in df.columns or col_ind not in df.columns:
        return None

    data = df.copy()
    # probeer indicator naar int om te zetten (True/False of 0/1)
    try:
        data[col_ind] = data[col_ind].astype(int)
    except Exception:
        # fallback: map True/False
        data[col_ind] = data[col_ind].map({True: 1, False: 0}).fillna(0).astype(int)

    if not group_labels:
        total = data[col_aantal].sum()
        if total == 0:
            return None
        doorstroom = (data[col_ind] * data[col_aantal]).sum()
        pct = 100 * doorstroom / total
        return pd.DataFrame({"groep": ["totaal"], "doorstroom_percentage": [pct]})

    # vertaal group_labels (labels) naar echte kolomnamen
    group_cols = [mapping[g] for g in group_labels if mapping.get(g) in df.columns]
    if not group_cols:
        return None

    grp = data.groupby(group_cols).apply(
        lambda g: 100 * (g[col_ind] * g[col_aantal]).sum() / g[col_aantal].sum()
        if g[col_aantal].sum() > 0
        else None
    )
    result = grp.reset_index(name="doorstroom_percentage")
    return result


def bereken_aandeel_van_totaal(df, mapping, group_label):
    """
    Berekent aandeel per categorie in group_label van het totale aantal studenten.
    Verwacht 'aantal_studenten' en een group_label dat via mapping naar een kolom verwijst.
    """
    col_aantal = mapping.get("aantal_studenten")
    col_group = mapping.get(group_label)

    if not col_aantal or not col_group:
        return None
    if col_aantal not in df.columns or col_group not in df.columns:
        return None

    data = df.copy()
    total = data[col_aantal].sum()
    if total == 0:
        return None

    agg = (
        data.groupby(col_group)[col_aantal]
        .sum()
        .reset_index(name="aantal_studenten")
    )
    agg["aandeel_percentage"] = 100 * agg["aantal_studenten"] / total
    return agg


def apply_filter(df, kolomnaam: str, label_text: str = None):
    """
    Generieke filterfunctie: toont een multiselect op kolom 'kolomnaam' en filtert de data.
    """
    if kolomnaam not in df.columns:
        return df

    unieke = sorted(df[kolomnaam].dropna().unique().tolist())
    if not label_text:
        label_text = f"Filter op '{kolomnaam}'"
    selectie = st.multiselect(
        label_text,
        options=unieke,
        default=unieke,
        key=f"filter_{kolomnaam}",
    )
    if selectie:
        return df[df[kolomnaam].isin(selectie)]
    return df


def suggest_default(label, cols):
    """
    Eenvoudige heuristiek om standaard kolommen te suggereren voor een label.
    """
    label_lower = label.lower()
    for c in cols:
        c_lower = c.lower()
        if label_lower in c_lower:
            return c
        if label == "regio" and ("regio" in c_lower or "arbeidsmarktregio" in c_lower):
            return c
        if label == "aantal_studenten" and (
            "aantal" in c_lower or "stud" in c_lower or "count" in c_lower
        ):
            return c
    return None


# ---------------- SIDEBAR: FILE UPLOAD ----------------
st.sidebar.header("1. Upload DUO CSV-bestand")

uploaded_file = st.sidebar.file_uploader(
    "Kies een CSV-bestand (DUO-export)", type=["csv"]
)

df = None

if uploaded_file is not None:
    tried = False

    # Probeer een paar veelvoorkomende combinaties
    for enc in ["utf-8", "latin-1"]:
        for sep in [",", ";", "\t"]:
            if tried:
                break
            try:
                df = pd.read_csv(uploaded_file, sep=sep, encoding=enc)
                tried = True
            except UnicodeDecodeError:
                continue
            except pd.errors.ParserError:
                continue

    if not tried:
        st.error(
            "Fout bij inlezen van het bestand. "
            "Probeer het bestand lokaal als 'CSV (UTF-8, komma of puntkomma)' op te slaan en opnieuw te uploaden."
        )
        df = None


if df is not None:
    st.sidebar.success("Bestand succesvol ingelezen.")

    # ---------------- DATA-INSPECTIE ----------------
    st.header("Gegevensinspectie en validatie")

    with st.expander("Toon voorbeeld van de ingelezen data"):
        st.dataframe(df.head())

    st.subheader("Basale datastatistieken")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Overzicht:**")
        st.write(f"Aantal rijen: {df.shape[0]}")
        st.write(f"Aantal kolommen: {df.shape[1]}")

    with col2:
        st.markdown("**Kolomnamen en datatypes:**")
        dtypes_df = pd.DataFrame(
            {"kolom": df.columns, "dtype": df.dtypes.astype(str)}
        )
        st.dataframe(dtypes_df)

    # Dimensies en metingen
    cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    num_cols = df.select_dtypes(include=["number"]).columns.tolist()

    st.markdown("**Automatisch herkende dimensies (categorisch):**")
    st.write(cat_cols if cat_cols else "Geen categorische kolommen gevonden.")

    st.markdown("**Automatisch herkende kengetallen (numeriek):**")
    st.write(num_cols if num_cols else "Geen numerieke kolommen gevonden.")

    # ---------------- KOLONNEN MATCHEN ----------------
    st.subheader("Koppel kolomnamen aan functionele labels")

    st.markdown(
        """
Selecteer voor elk functioneel **label** welke kolom uit de CSV daarbij hoort.
Zo hoef je de code niet aan te passen als een extract andere kolomnamen gebruikt.
"""
    )

    available_cols = df.columns.tolist()

    functionele_labels = {
        "instroomjaar": "Jaar van instroom / cohort (bijv. 2022-2023)",
        "aantal_studenten": "Aantal studenten / telling in de groep",
        "sector": "Sector / opleidingsdomein (bijv. techniek, zorg, economie)",
        "regio": "Regio of arbeidsmarktregio",
        "doorstroom_indicator": "Indicator doorstroom mbo-hbo (0/1 of True/False)",
        "brin_mbo": "BRIN-code mbo-instelling",
        "brin_hbo": "BRIN-code hbo-instelling",
        "niveau_mbo": "Mbo-niveau (bijv. 2, 3, 4)",
        "opleiding_mbo": "Opleiding mbo",
        "opleiding_hbo": "Opleiding hbo",
    }

    if "kolom_mapping" not in st.session_state:
        st.session_state["kolom_mapping"] = {}

    kolom_mapping = st.session_state["kolom_mapping"]

    col_left, col_right = st.columns(2)

    labels_items = list(functionele_labels.items())
    mid = len(labels_items) // 2

    with col_left:
        for label, beschrijving in labels_items[:mid]:
            st.markdown(f"**{label}** – {beschrijving}")
            default_col = kolom_mapping.get(label, suggest_default(label, available_cols))
            default_index = (
                (["(geen)"] + available_cols).index(default_col)
                if default_col in available_cols
                else 0
            )
            gekozen = st.selectbox(
                f"Kies kolom voor '{label}'",
                options=["(geen)"] + available_cols,
                index=default_index,
                key=f"mapping_{label}",
            )
            kolom_mapping[label] = None if gekozen == "(geen)" else gekozen

    with col_right:
        for label, beschrijving in labels_items[mid:]:
            st.markdown(f"**{label}** – {beschrijving}")
            default_col = kolom_mapping.get(label, suggest_default(label, available_cols))
            default_index = (
                (["(geen)"] + available_cols).index(default_col)
                if default_col in available_cols
                else 0
            )
            gekozen = st.selectbox(
                f"Kies kolom voor '{label}'",
                options=["(geen)"] + available_cols,
                index=default_index,
                key=f"mapping_{label}",
            )
            kolom_mapping[label] = None if gekozen == "(geen)" else gekozen

    st.session_state["kolom_mapping"] = kolom_mapping

    st.info(
        "De gekozen kolommen worden gebruikt in de standaardviews en kengetallen. "
        "Je kunt deze mapping later altijd wijzigen."
    )

    # Verkorte variabelen voor veelgebruikte labels
    m = kolom_mapping
    col_instroomjaar = m.get("instroomjaar")
    col_aantal = m.get("aantal_studenten")
    col_sector = m.get("sector")
    col_regio = m.get("regio")
    col_doorstroom = m.get("doorstroom_indicator")

    # ---------------- TABS ----------------
    tab_over_time, tab_sector, tab_regio_tab, tab_custom, tab_kpi = st.tabs(
        [
            "Ontwikkeling door de tijd",
            "Per sector",
            "Per regio",
            "Vrije analyse",
            "Kengetallen & indicatoren",
        ]
    )

    # -------- TAB 1: ONTWIKKELING DOOR DE TIJD --------
    with tab_over_time:
        st.subheader("Ontwikkeling aantal studenten door de tijd (standaardview)")

        if col_instroomjaar and col_aantal:
            if col_instroomjaar in df.columns and col_aantal in df.columns:
                df_time = df.copy()

                cols_time = st.columns(2)
                with cols_time[0]:
                    if col_sector:
                        df_time = apply_filter(df_time, col_sector, "Filter op sector")
                with cols_time[1]:
                    if col_regio:
                        df_time = apply_filter(df_time, col_regio, "Filter op regio")

                kleur_dim_opties = ["(geen)"]
                if col_sector:
                    kleur_dim_opties.append("sector")
                if col_regio:
                    kleur_dim_opties.append("regio")

                kleur_label = st.selectbox(
                    "Kleur/groepering (bijv. sector of regio)",
                    options=kleur_dim_opties,
                    key="kleur_tijd",
                )
                kleur_col = None
                if kleur_label == "sector" and col_sector:
                    kleur_col = col_sector
                if kleur_label == "regio" and col_regio:
                    kleur_col = col_regio

                fig_time = px.line(
                    df_time,
                    x=col_instroomjaar,
                    y=col_aantal,
                    color=kleur_col,
                    markers=True,
                    title="Aantal studenten per instroomjaar",
                )
                fig_time.update_layout(
                    xaxis_title=col_instroomjaar,
                    yaxis_title=col_aantal,
                    legend_title=kleur_label if kleur_col else "Categorie",
                )
                st.plotly_chart(fig_time, use_container_width=True)
            else:
                st.warning(
                    "De via mapping gekozen kolommen voor instroomjaar of aantal studenten bestaan niet in de data."
                )
        else:
            st.info(
                "Koppel eerst een kolom aan 'instroomjaar' en 'aantal_studenten' in de mapping hierboven."
            )

    # -------- TAB 2: PER SECTOR --------
    with tab_sector:
        st.subheader("Verdeling en ontwikkeling per sector")

        if col_sector and col_aantal and col_sector in df.columns and col_aantal in df.columns:
            df_sec = df.copy()

            if col_instroomjaar and col_instroomjaar in df_sec.columns:
                jaren_beschikbaar = sorted(
                    df_sec[col_instroomjaar].dropna().unique().tolist()
                )
                gekozen_jaren = st.multiselect(
                    "Kies instroomjaren voor de sectoranalyse",
                    options=jaren_beschikbaar,
                    default=jaren_beschikbaar,
                    key="jaren_sector",
                )
                if gekozen_jaren:
                    df_sec = df_sec[df_sec[col_instroomjaar].isin(gekozen_jaren)]

            if col_regio and col_regio in df_sec.columns:
                df_sec = apply_filter(df_sec, col_regio, "Filter op regio")

            # Staafdiagram: aantal studenten per sector
            fig_sector_bar = px.bar(
                df_sec,
                x=col_sector,
                y=col_aantal,
                color=col_sector,
                title="Aantal studenten per sector",
            )
            fig_sector_bar.update_layout(
                xaxis_title="Sector",
                yaxis_title="Aantal studenten",
                showlegend=False,
            )
            st.plotly_chart(fig_sector_bar, use_container_width=True)

            # Lijn: ontwikkeling per sector (indien instroomjaar aanwezig)
            if col_instroomjaar and col_instroomjaar in df_sec.columns:
                fig_sector_line = px.line(
                    df_sec,
                    x=col_instroomjaar,
                    y=col_aantal,
                    color=col_sector,
                    markers=True,
                    title="Ontwikkeling aantal studenten per sector",
                )
                fig_sector_line.update_layout(
                    xaxis_title=col_instroomjaar,
                    yaxis_title=col_aantal,
                    legend_title="Sector",
                )
                st.plotly_chart(fig_sector_line, use_container_width=True)
        else:
            st.info(
                "Koppel eerst kolommen aan 'sector' en 'aantal_studenten' in de mapping hierboven."
            )

    # -------- TAB 3: PER REGIO --------
    with tab_regio_tab:
        st.subheader("Verdeling en ontwikkeling per regio")

        if col_regio and col_aantal and col_regio in df.columns and col_aantal in df.columns:
            df_reg = df.copy()

            if col_instroomjaar and col_instroomjaar in df_reg.columns:
                jaren_beschikbaar = sorted(
                    df_reg[col_instroomjaar].dropna().unique().tolist()
                )
                gekozen_jaren = st.multiselect(
                    "Kies instroomjaren voor de regioanalyse",
                    options=jaren_beschikbaar,
                    default=jaren_beschikbaar,
                    key="jaren_regio",
                )
                if gekozen_jaren:
                    df_reg = df_reg[df_reg[col_instroomjaar].isin(gekozen_jaren)]

            if col_sector and col_sector in df_reg.columns:
                df_reg = apply_filter(df_reg, col_sector, "Filter op sector")

            # Staafdiagram per regio
            fig_reg_bar = px.bar(
                df_reg,
                x=col_regio,
                y=col_aantal,
                color=col_regio,
                title="Aantal studenten per regio",
            )
            fig_reg_bar.update_layout(
                xaxis_title="Regio",
                yaxis_title="Aantal studenten",
                showlegend=False,
            )
            st.plotly_chart(fig_reg_bar, use_container_width=True)

            # Lijn: ontwikkeling per regio
            if col_instroomjaar and col_instroomjaar in df_reg.columns:
                fig_reg_line = px.line(
                    df_reg,
                    x=col_instroomjaar,
                    y=col_aantal,
                    color=col_regio,
                    markers=True,
                    title="Ontwikkeling aantal studenten per regio",
                )
                fig_reg_line.update_layout(
                    xaxis_title=col_instroomjaar,
                    yaxis_title=col_aantal,
                    legend_title="Regio",
                )
                st.plotly_chart(fig_reg_line, use_container_width=True)
        else:
            st.info(
                "Koppel eerst kolommen aan 'regio' en 'aantal_studenten' in de mapping hierboven."
            )

    # -------- TAB 4: VRIJE ANALYSE --------
    with tab_custom:
        st.subheader("Vrije analyse (zelf assen en grafiektype kiezen)")

        if not num_cols:
            st.info("Er zijn geen numerieke kolommen gevonden voor de Y-as.")
        else:
            chart_type = st.radio(
                "Kies een type visualisatie",
                options=["Lijngrafiek", "Staafdiagram", "Spreidingsdiagram", "Treemap"],
                key="chart_type_custom",
            )

            # Standaard X- en Y-voorstel
            x_default = col_instroomjaar if col_instroomjaar in (cat_cols + num_cols) else None
            y_default = col_aantal if col_aantal in num_cols else None

            x_axis = st.selectbox(
                "X-as",
                options=cat_cols + num_cols,
                index=(cat_cols + num_cols).index(x_default)
                if x_default in (cat_cols + num_cols)
                else 0,
                key="custom_x",
            )

            y_axis = st.selectbox(
                "Y-as (numeriek kengetal)",
                options=num_cols,
                index=num_cols.index(y_default) if y_default in num_cols else 0,
                key="custom_y",
            )

            kleur_dim = st.selectbox(
                "Kleur/groepering (optioneel)",
                options=["(geen)"] + cat_cols,
                key="custom_color",
            )

            filter_col = st.selectbox(
                "Kolom om op te filteren (optioneel)",
                options=["(geen)"] + cat_cols,
                key="custom_filter",
            )

            df_filtered = df.copy()
            if filter_col != "(geen)":
                df_filtered = apply_filter(df_filtered, filter_col, f"Filter op {filter_col}")

            warnings = []
            if y_axis not in num_cols:
                warnings.append("Y-as moet numeriek zijn.")
            if (
                chart_type in ["Lijngrafiek", "Staafdiagram", "Spreidingsdiagram"]
                and x_axis not in df_filtered.columns
            ):
                warnings.append("Ongeldige X-as geselecteerd.")
            if chart_type == "Treemap" and x_axis not in df_filtered.columns:
                warnings.append("Voor een treemap is een geldige dimensie (X-as) nodig.")

            if warnings:
                for msg in warnings:
                    st.warning(msg)
            else:
                kleur_argument = None if kleur_dim == "(geen)" else kleur_dim

                try:
                    if chart_type == "Lijngrafiek":
                        fig = px.line(
                            df_filtered,
                            x=x_axis,
                            y=y_axis,
                            color=kleur_argument,
                            markers=True,
                            title=f"Lijngrafiek: {y_axis} per {x_axis}",
                        )
                    elif chart_type == "Staafdiagram":
                        fig = px.bar(
                            df_filtered,
                            x=x_axis,
                            y=y_axis,
                            color=kleur_argument,
                            barmode="group",
                            title=f"Staafdiagram: {y_axis} per {x_axis}",
                        )
                    elif chart_type == "Spreidingsdiagram":
                        fig = px.scatter(
                            df_filtered,
                            x=x_axis,
                            y=y_axis,
                            color=kleur_argument,
                            title=f"Spreidingsdiagram: {y_axis} vs {x_axis}",
                        )
                    elif chart_type == "Treemap":
                        path = [x_axis] if kleur_argument is None else [x_axis, kleur_argument]
                        fig = px.treemap(
                            df_filtered,
                            path=path,
                            values=y_axis,
                            title=f"Treemap: {y_axis} naar {x_axis}",
                        )

                    fig.update_layout(
                        xaxis_title=x_axis,
                        yaxis_title=y_axis,
                        legend_title=kleur_argument if kleur_argument else "Categorie",
                    )
                    st.plotly_chart(fig, use_container_width=True)
                except Exception as e:
                    st.error(f"Fout bij genereren van de grafiek: {e}")

    # -------- TAB 5: KENGETALLEN & INDICATOREN --------
    with tab_kpi:
        st.subheader("Kengetallen & indicatoren (doorstroom en aandeel)")

        st.markdown(
            """
Deze tab rekent enkele basisindicatoren uit op basis van **aantal_studenten** 
en **doorstroom_indicator** (0/1). Gebruik de filters om specifieke cohorten of groepen te analyseren.
"""
        )

        df_kpi = df.copy()

        cols_kpi = st.columns(3)
        with cols_kpi[0]:
            if col_instroomjaar and col_instroomjaar in df_kpi.columns:
                jaren = sorted(df_kpi[col_instroomjaar].dropna().unique().tolist())
                gekozen_jaren = st.multiselect(
                    "Filter op instroomjaar",
                    options=jaren,
                    default=jaren,
                    key="kpi_jaren",
                )
                if gekozen_jaren:
                    df_kpi = df_kpi[df_kpi[col_instroomjaar].isin(gekozen_jaren)]

        with cols_kpi[1]:
            if col_sector and col_sector in df_kpi.columns:
                df_kpi = apply_filter(df_kpi, col_sector, "Filter op sector (KPI)")

        with cols_kpi[2]:
            if col_regio and col_regio in df_kpi.columns:
                df_kpi = apply_filter(df_kpi, col_regio, "Filter op regio (KPI)")

        # 1. Totaal doorstroompercentage
        st.markdown("### 1. Totaal doorstroompercentage mbo–hbo")

        totaal_pct_df = bereken_doorstroompercentage(df_kpi, m, group_labels=None)
        if totaal_pct_df is None:
            st.info(
                "Voor deze indicator zijn kolommen voor 'doorstroom_indicator' en 'aantal_studenten' nodig in de mapping."
            )
        else:
            st.dataframe(
                totaal_pct_df.style.format({"doorstroom_percentage": "{:.1f}%"}),
                use_container_width=True,
            )

        # 2. Doorstroompercentage per sector
        st.markdown("### 2. Doorstroompercentage per sector")

        if col_sector and col_sector in df_kpi.columns:
            pct_sector_df = bereken_doorstroompercentage(df_kpi, m, group_labels=["sector"])
            if pct_sector_df is not None:
                pct_sector_df = pct_sector_df.rename(columns={col_sector: "sector"})
                st.dataframe(
                    pct_sector_df.style.format({"doorstroom_percentage": "{:.1f}%"}),
                    use_container_width=True,
                )

                fig_pct_sector = px.bar(
                    pct_sector_df,
                    x="sector",
                    y="doorstroom_percentage",
                    title="Doorstroompercentage mbo–hbo per sector",
                )
                fig_pct_sector.update_layout(
                    xaxis_title="Sector",
                    yaxis_title="Doorstroompercentage",
                )
                st.plotly_chart(fig_pct_sector, use_container_width=True)
            else:
                st.info(
                    "Kon geen doorstroompercentage per sector berekenen (controleer mapping en data)."
                )
        else:
            st.info("Koppel eerst een kolom aan 'sector' in de mapping.")

        # 3. Doorstroompercentage per regio
        st.markdown("### 3. Doorstroompercentage per regio")

        if col_regio and col_regio in df_kpi.columns:
            pct_regio_df = bereken_doorstroompercentage(df_kpi, m, group_labels=["regio"])
            if pct_regio_df is not None:
                pct_regio_df = pct_regio_df.rename(columns={col_regio: "regio"})
                st.dataframe(
                    pct_regio_df.style.format({"doorstroom_percentage": "{:.1f}%"}),
                    use_container_width=True,
                )

                fig_pct_regio = px.bar(
                    pct_regio_df,
                    x="regio",
                    y="doorstroom_percentage",
                    title="Doorstroompercentage mbo–hbo per regio",
                )
                fig_pct_regio.update_layout(
                    xaxis_title="Regio",
                    yaxis_title="Doorstroompercentage",
                )
                st.plotly_chart(fig_pct_regio, use_container_width=True)
            else:
                st.info(
                    "Kon geen doorstroompercentage per regio berekenen (controleer mapping en data)."
                )
        else:
            st.info("Koppel eerst een kolom aan 'regio' in de mapping.")

        # 4. Aandeel van totaal per sector/regio
        st.markdown("### 4. Aandeel van totaal (verdeling)")

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**Aandeel per sector**")
            if col_sector and col_sector in df_kpi.columns:
                aandeel_sector_df = bereken_aandeel_van_totaal(df_kpi, m, "sector")
                if aandeel_sector_df is not None:
                    st.dataframe(
                        aandeel_sector_df.style.format(
                            {"aandeel_percentage": "{:.1f}%"}
                        ),
                        use_container_width=True,
                    )
            else:
                st.info("Koppel eerst een kolom aan 'sector' in de mapping.")

        with col_b:
            st.markdown("**Aandeel per regio**")
            if col_regio and col_regio in df_kpi.columns:
                aandeel_regio_df = bereken_aandeel_van_totaal(df_kpi, m, "regio")
                if aandeel_regio_df is not None:
                    st.dataframe(
                        aandeel_regio_df.style.format(
                            {"aandeel_percentage": "{:.1f}%"}
                        ),
                        use_container_width=True,
                    )
            else:
                st.info("Koppel eerst een kolom aan 'regio' in de mapping.")

else:
    st.info("Upload een DUO CSV-bestand in de sidebar om te beginnen.")
