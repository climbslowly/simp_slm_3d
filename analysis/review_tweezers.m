function result = review_tweezers(resultDir, darkScan, parameterFile, outputDir)
% REVIEW_TWEEZERS 与Python一致的暗场审计、径向亮度、方向间距及孔径敏感性。
% 输入：已有逐阱输出目录、单张暗场扫描目录、共用JSON、独立输出目录。
% 不连接硬件、不自动扣暗场；均值/总体标准差是单帧空间统计，不是时间噪声。
resultDir=canonical(resultDir);darkScan=canonical(darkScan);outputDir=canonical(outputDir);
r=load(fullfile(resultDir,'tweezers.mat'));p=jsondecode(r.parameters_json);
q=jsondecode(fileread(parameterFile));scan=canonical(r.source);
assert(q.algorithm_version==1);
assert(q.neighbor_distance_ratios(1)>0 && q.neighbor_distance_ratios(2)>q.neighbor_distance_ratios(1));
assert(all(diff(q.radial_edges_nominal_um)>0));
assert(all(q.aperture_radii_px>0 & q.aperture_radii_px==floor(q.aperture_radii_px) & q.aperture_radii_px<p.spots.background_annulus_inner_px));
for src={scan,darkScan,resultDir}
    assert(~strcmpi(outputDir,src{1}) && ~startsWith(lower(outputDir),lower([src{1} filesep])), '输出必须在输入目录外');
end
logs=readtable(fullfile(scan,'scan_log.csv'),'TextType','string','VariableNamingRule','preserve');
dlogs=readtable(fullfile(darkScan,'scan_log.csv'),'TextType','string','VariableNamingRule','preserve');
j=find(logs.point_id==p.spots.reference_point_id);k=find(dlogs.status=="ok");
assert(isscalar(j) && logs.status(j)=="ok" && isscalar(k));
raw=imread(safeFile(scan,logs.filename(j)));dark=imread(safeFile(darkScan,dlogs.filename(k)));
rm=load(safeFile(scan,logs.mat_filename(j)),'image');dm=load(safeFile(darkScan,dlogs.mat_filename(k)),'image');
stats=[frameStats(raw,logs.exposure_us(j),rm.image);frameStats(dark,dlogs.exposure_us(k),dm.image)];
s=r.spots;good=s(:,12)==0 & s(:,10)>0 & s(:,11)>0;t=s(good,:);
radius=sqrt(sum(t(:,7:8).^2,2));
summary=[size(s,1),size(t,1),cv(t(:,10)),cv(t(:,11)),median(s(:,15)),cv(s(:,15)), ...
    correlation(radius,t(:,10)),correlation(t(:,10),t(:,11)),median(t(:,13)),median(t(:,14))];
summary_columns={'candidates','valid_spots','integral_cv','peak_cv','nn_median_px','nn_cv', ...
    'radius_integral_pearson','integral_peak_pearson','median_sigma_x_px','median_sigma_y_px'};
radial=nan(numel(q.radial_edges_nominal_um)-1,6);
for i=1:size(radial,1)
    lo=q.radial_edges_nominal_um(i);hi=q.radial_edges_nominal_um(i+1);
    a=t(radius>=lo & radius<hi,10);
    radial(i,:)=[lo,hi,numel(a),mean(a),mean(a)/mean(t(:,10)),cv(a)];
end
% 两点只计一次；距离带为最近邻中位数的0.75~1.25倍，去掉方格对角线。
xy=s(:,5:6);pitch=median(s(:,15));rows=cell(size(s,1)-1,1);
for i=1:size(s,1)-1
    d=xy(i+1:end,:)-xy(i,:);len=sqrt(sum(d.^2,2));
    keep=find(len>=pitch*q.neighbor_distance_ratios(1) & len<=pitch*q.neighbor_distance_ratios(2));
    g=1+(abs(d(keep,1))<abs(d(keep,2)));
    rows{i}=[repmat(i,numel(keep),1),keep+i,d(keep,:),len(keep),g];
end
edges=vertcat(rows{:});axes=nan(2,6);
for g=1:2
    e=edges(edges(:,6)==g,:);v=e(:,3:4);v(v(:,g)<0,:)=-v(v(:,g)<0,:);
    angle=atan2d(mean(v(:,2)),mean(v(:,1)));med=median(e(:,5));
    axes(g,:)=[g,size(e,1),med,med*r.calibration(2),cv(e(:,5)),angle];
end
% 仅重算原始图的圆孔积分，沿用12~14px环背景；不读取Python复查输出。
br=p.spots.background_annulus_outer_px;[xx,yy]=meshgrid(-br:br);rr=xx.^2+yy.^2;
ann=rr>=p.spots.background_annulus_inner_px^2 & rr<=br^2;
apertures=nan(numel(q.aperture_radii_px),4);
for a=1:numel(q.aperture_radii_px)
    rad=q.aperture_radii_px(a);mask=rr<=rad^2;values=nan(size(s,1),1);
    for i=1:size(s,1)
        x=floor(s(i,2)+.5);y=floor(s(i,3)+.5);
        if x-br<0 || y-br<0 || x+br>=size(raw,2) || y+br>=size(raw,1),continue;end
        patch=double(raw(y-br+1:y+br+1,x-br+1:x+br+1));b=median(patch(ann));v=patch(mask);
        total=sum(v-b);
        if all(v<p.candidate_clip_count) && total>0 && max(v)>b,values(i)=total;end
    end
    values=values(isfinite(values));apertures(a,:)=[rad,nnz(mask),numel(values),cv(values)];
end
result=struct('stats',stats,'summary',summary,'summary_columns',{summary_columns},'radial',radial, ...
    'edges',edges,'axes',axes,'apertures',apertures,'source',scan,'dark_source',darkScan, ...
    'result_source',resultDir,'parameters_json',fileread(parameterFile),'original_parameters_json',r.parameters_json);
if ~isfolder(outputDir),mkdir(outputDir);end
save(fullfile(outputDir,'review.mat'),'-struct','result','-v7');
writetable(array2table(summary,'VariableNames',summary_columns),fullfile(outputDir,'summary.csv'));
writetable(array2table(radial,'VariableNames',{'r_start_nominal_um','r_end_nominal_um','count','mean_net_sum','relative_mean','cv'}),fullfile(outputDir,'radial.csv'));
writetable(array2table(axes,'VariableNames',{'group','edge_count','median_px','median_nominal_um','cv','angle_deg'}),fullfile(outputDir,'axes.csv'));
writetable(array2table(apertures,'VariableNames',{'radius_px','area_px','valid_count','integral_cv'}),fullfile(outputDir,'apertures.csv'));
reasons={};
if ~strcmp(class(raw),class(dark)),reasons{end+1}='different stored pixel dtype/count encoding';end
if ~isequal(size(raw),size(dark)),reasons{end+1}='different image shape';end
if logs.exposure_us(j)~=dlogs.exposure_us(k),reasons{end+1}='different exposure';end
if string(logs.camera_serial(j))~=string(dlogs.camera_serial(k)),reasons{end+1}='different camera serial';end
reasons{end+1}='gain/pixel-format/compensation historical readback not recorded';
audit=struct('dark_correction_applied',false,'direct_subtraction_supported',false, ...
    'reasons',{reasons},'science_dtype',class(raw),'dark_dtype',class(dark),'dark_successful_frames',1,'reported_settings',q);
f=fopen(fullfile(outputDir,'dark_audit.json'),'w');cleanup=onCleanup(@()fclose(f));
fprintf(f,'%s',jsonencode(audit,'PrettyPrint',true));
disp(summary);
end

function v=frameStats(im,exposure,matImage)
info=whos('im');d=double(im);
v=[size(im),info.bytes/numel(im),min(d(:)),max(d(:)),mean(d(:)),std(d(:),1),mean(d(:)==0),exposure,isequal(im,matImage)];
end
function v=cv(x)
if isempty(x) || mean(x)==0,v=NaN;else,v=std(x,1)/mean(x);end
end
function v=correlation(x,y)
if numel(x)<2 || std(x,1)==0 || std(y,1)==0,v=NaN;else,c=corrcoef(x,y);v=c(1,2);end
end
function p=canonical(p)
p=char(java.io.File(char(p)).getCanonicalPath());
end
function p=safeFile(root,relative)
p=canonical(fullfile(root,char(relative)));
assert(startsWith(lower(p),lower([root filesep])),'路径越出输入目录');
end
